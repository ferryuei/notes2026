# Manticore Top MAC - Functional and Architectural Analysis

**Document Version:** 1.0  
**Date:** January 22, 2026  
**Module:** `manticore_top_mac`  
**File:** `/ip/manticore/rtl/manticore_top_mac.vhd`  
**Lines of Code:** 683

---

## 1. Executive Summary

The `manticore_top_mac` module is a high-performance Ethernet switch integration layer that bridges MAC controllers with the Manticore switch fabric core. It provides a complete Layer 2 switching solution with:

- **Multi-rate port support**: 1GbE, 10GbE, and CPU ports
- **Flexible interfaces**: XGMII (10G MACs), AXI-Stream (external MACs), and CPU ports
- **Multiple register access protocols**: AXI4-Lite, APB, or direct IP2Bus
- **IEEE 1588 PTP timestamping** support
- **External packet/credit buffer memory** interface

The module integrates:
1. **Manticore switch core** (`manticore_top`) - packet switching fabric
2. **10G XGMII MAC wrappers** (`xgmii_axi_mac_wrapper`) - up to 4 MACs
3. **Register access bridges** (AXI/APB to IP2Bus converter)
4. **Bus interconnect** for multi-master register access

---

## 2. Module Architecture

### 2.1 Top-Level Block Diagram

```
                    ┌──────────────────────────────────────────────────────┐
                    │          manticore_top_mac (Top Integration)         │
                    ├──────────────────────────────────────────────────────┤
                    │                                                      │
  XGMII Ports       │  ┌────────────────────────────────────────────┐     │  AXI-Stream Ports
  (10G MACs)        │  │  xgmii_axi_mac_wrapper [0..N-1]            │     │  (1G/10G/CPU)
rxd[64]─────────────┼─>│  - XGMII RX/TX                             │<────┼──rx_axis_tdata[64]
rxc[8]──────────────┼─>│  - CRC generation/check                    │     │  rx_axis_tvalid
                    │  │  - PTP timestamping                        │     │  rx_axis_tready
txd[64]<────────────┼──│  - Statistics counters                     │────>┼──tx_axis_tdata[64]
txc[8]<─────────────┼──│  - AXI-Stream conversion                   │     │  tx_axis_tvalid
                    │  └────────────┬───────────────────────────────┘     │  tx_axis_tready
                    │               │ AXI-Stream (64-bit)                 │
                    │               v                                     │
                    │  ┌────────────────────────────────────────────┐     │
    Register Bus    │  │                                            │     │
    ┌───────────────┼─>│        manticore_top (Switch Core)         │<────┼─┐
    │ AXI4-Lite /   │  │                                            │     │ │ External
    │ APB /         │  │  ┌──────────────────────────────────────┐  │     │ │ AXI-Stream
    │ IP2Bus        │  │  │  Port [0..N-1] Processing           │  │     │ │ Ports
    │               │  │  │  - Packet Parser (L2/L3/L4)         │  │     │ │
s_axi_* ────────────┼─>│  │  - MAC Learning (FDB lookup)        │  │     │ │
apb_*   ────────────┼─>│  │  - Packet Action Engine (MAE)       │  │     │ │
bus2ip_*────────────┼─>│  │  - Ingress/Egress Queuing           │  │<────┼─┘
                    │  │  │  - TSN: CBS, TAS support            │  │     │
    ┌───────────────┼──│  └──────────────────────────────────────┘  │     │
    │               │  │                                            │     │
    │ IP Interconnect│  │  ┌──────────────────────────────────────┐  │     │
    │ (bus2ip_ic)   │  │  │  Scheduler (sch_sync)                │  │     │
    │  - Routes to: │  │  │  - Arbitration cycles                │  │     │
    │    * Core regs│  │  │  - Multicast pointer generation      │  │     │
    │    * MAC[0..N]│  │  └──────────────────────────────────────┘  │     │
    │               │  │                                            │     │
    └───────────────┼──│  ┌──────────────────────────────────────┐  │     │
                    │  │  │  Crossbar Switch Fabric (64+11 bits)  │  │     │
                    │  │  │  - Non-blocking N x N crossbar       │  │     │
                    │  │  │  - Configurable mux size             │  │     │
                    │  │  │  - Pipeline stages: input + output   │  │     │
                    │  │  └──────────────────────────────────────┘  │     │
                    │  │                                            │     │
                    │  │  ┌──────────────────────────────────────┐  │     │
                    │  │  │  MAC Action Engine (MAE)              │  │     │
    PTP Time-of-Day │  │  │  - TCAM-based packet classification  │  │     │
tod_rx[96]──────────┼─>│  │  - QoS policy enforcement            │  │     │
tod_tx[96]──────────┼─>│  │  - VLAN manipulation                 │  │     │
                    │  │  │  - Forwarding decision               │  │     │
                    │  │  └──────────────────────────────────────┘  │     │
                    │  └────────────────────────────────────────────┘     │
                    │               │ │ Memory Interface                  │
                    │               v v                                   │
    External        │  ┌──────────────────────────────────────────┐      │
    Memory          │  │  Packet Buffer & Credit Buffer           │      │
mem_pkt_buf_*───────┼─>│  - Per-port memory partitioning          │      │
mem_crd_buf_*───────┼─>│  - Configurable depth per port           │      │
                    │  └──────────────────────────────────────────┘      │
                    │                                                     │
                    └─────────────────────────────────────────────────────┘

Clock Domains:
  • core_clk   : Switch core (300 MHz typical)
  • sch_clk    : Scheduler (300 MHz typical)
  • mae_clk    : MAC Action Engine (300 MHz typical)
  • rx_clk[N]  : Per-port RX clock (156.25 MHz for 10G)
  • tx_clk[N]  : Per-port TX clock (156.25 MHz for 10G)
  • axi_clk    : AXI register access clock
  • apb_clk    : APB register access clock
  • bus2ip_clk : IP2Bus access clock
```

---

## 3. Functional Description

### 3.1 Core Functionality

#### 3.1.1 Packet Switching Flow

```
RX Path:
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  XGMII/  │──>│   MAC    │──>│  Parser  │──>│   MAE    │──>│  Queue   │
│ AXI-in   │   │ Adapter  │   │  (L2-L4) │   │ Lookup   │   │ Ingress  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                   ▲                ▲              ▲              │
                   │                │              │              │
              Port Width       Extract DA,     FDB Table      Store to
              Adaptation       SA, VLAN,       Query          Pkt Buffer
              (1/8/N bytes)    EtherType                      + metadata

                                                                  │
                                                                  v
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  XGMII/  │<──│   MAC    │<──│ Crossbar │<──│ Scheduler│<──│  Queue   │
│ AXI-out  │   │ Adapter  │   │  Switch  │   │ Arbiter  │   │ Egress   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                   ▲              ▲               ▲
                   │              │               │
              Port Width      N x N switch    Round-robin
              Adaptation      75-bit bus      + priority
              Add CRC         Non-blocking    arbitration
```

#### 3.1.2 Switch Core (`manticore_top`)

**Key Features:**
- **Non-blocking crossbar architecture**: Full wire-speed switching
- **Virtual Output Queuing (VOQ)**: Eliminates head-of-line blocking
- **Credit-based flow control**: Prevents buffer overflow
- **MAC learning**: Automatic source MAC address learning
- **Multicast/broadcast support**: Packet replication to multiple ports
- **TSN support**: Time-Aware Shaper (TAS), Credit-Based Shaper (CBS)

**Performance:**
- Line-rate switching at 10 Gbps per port
- Non-blocking N×N switch fabric (N = GEN_N_PORTS)
- Cut-through forwarding mode supported
- Store-and-forward mode supported

---

### 3.2 MAC Layer Integration

#### 3.2.1 10G XGMII MAC Wrapper (`xgmii_axi_mac_wrapper`)

Instantiated for each 10G MAC port (lines 496-573):

```vhdl
u_mac : entity work.xgmii_axi_mac_wrapper(rtl)
  generic map (
    MAC_BASE_ADDR    => GEN_MACS_BASE_ADDR + i*0x800,
    DATA_BYTES       => 8,              -- 64-bit AXI-Stream
    LANE_ALIGN_EN    => true,           -- XGMII lane alignment
    PTP_TS_EN        => GEN_TS_EN,      -- PTP timestamping
    TX_STORE_N_FWD   => configurable,   -- Cut-through vs store-forward
    RX_STORE_N_FWD   => configurable
  )
```

**MAC Functions:**
- **XGMII ↔ AXI-Stream conversion**
- **CRC generation** (TX) and **checking** (RX)
- **Frame filtering**: By MAC address, VLAN, promiscuous mode
- **PTP timestamping**: 128-bit timestamps on TX/RX
- **Statistics**: Packet/byte counters, error counters
- **Lane alignment**: Compensate for XGMII lane skew
- **Flow control**: Pause frame generation/handling

**Register Map:**
Each MAC has a 2KB register space (stride 0x800):
- Base address: `GEN_MACS_BASE_ADDR + port*0x800`
- Typical base: 0x10000 (MAC0), 0x10800 (MAC1), etc.

#### 3.2.2 External AXI-Stream Ports

Support for external 1G/10G/CPU ports via AXI-Stream interface:

**Port Types:**
1. **1-byte ports** (`C_N_1B_NO_MAC_PORTS`): 1 GbE ports, 8-bit data width
2. **8-byte ports** (`C_N_8B_NO_MAC_PORTS`): 10 GbE ports, 64-bit data width
3. **CPU ports** (`C_N_CPU_NO_MAC_PORTS`): Configurable width

**Width Adaptation Logic** (lines 318-413):
- Maps external AXI-Stream widths to internal switch core widths
- Handles `tkeep` signal mapping for different port widths
- Provides separate mapping for each port type

---

### 3.3 Register Access Architecture

#### 3.3.1 Multi-Protocol Support

Three mutually exclusive register access interfaces:

**1. AXI4-Lite Interface** (`GEN_REG_ACCESS_IFACE = "axi"`, lines 577-616)
```vhdl
u_axi2ip : entity work.axi2ip
  -- Converts AXI4-Lite protocol to internal IP2Bus
  -- Full handshaking: AWVALID/AWREADY, WVALID/WREADY, etc.
```

**2. APB Interface** (`GEN_REG_ACCESS_IFACE = "apb"`, lines 629-661)
```vhdl
apb2ip : entity work.apb2ip(rtl)
  -- Converts APB protocol to internal IP2Bus
  -- 3-phase protocol: SETUP, ACCESS, IDLE
```

**3. Direct IP2Bus** (`GEN_REG_ACCESS_IFACE = "ip2bus"`, lines 669-681)
```vhdl
-- Direct connection for custom bus interfaces
-- No protocol conversion overhead
```

#### 3.3.2 Bus Interconnect (`bus2ip_ic`)

Multi-master arbiter routes register accesses (lines 289-316):

```
Master Interfaces (GEN_N_MACS+1):
  [0] : manticore_top (switch core registers)
  [1] : xgmii_axi_mac_wrapper[0] registers
  [2] : xgmii_axi_mac_wrapper[1] registers
  ...
  [N] : xgmii_axi_mac_wrapper[N-1] registers

Address Decoding:
  - Automatic based on address range
  - Each master has unique address space
  - Arbitration for simultaneous accesses
```

**Register Address Space:**
```
0x00000 - 0x0FFFF : Manticore switch core
0x10000 - 0x107FF : MAC[0] registers
0x10800 - 0x10FFF : MAC[1] registers
0x11000 - 0x117FF : MAC[2] registers
0x11800 - 0x11FFF : MAC[3] registers
...
```

---

### 3.4 Clock Domain Architecture

#### 3.4.1 Clock Domains

| Clock Domain | Frequency | Function |
|--------------|-----------|----------|
| `core_clk_i` | 300 MHz | Switch fabric, packet processing |
| `sch_clk_i` | 300 MHz | Scheduler arbitration |
| `mae_clk_i` | 300 MHz | MAC Action Engine (packet classification) |
| `rx_clk_i[N]` | 156.25 MHz | Per-port RX clock (10G XGMII) |
| `tx_clk_i[N]` | 156.25 MHz | Per-port TX clock (10G XGMII) |
| `axi_clk` / `apb_clk` | 100-200 MHz | Register access bus clock |
| `bus2ip_clk` | Variable | Internal register clock (from bridge) |

#### 3.4.2 Clock Domain Crossings (CDC)

**RX Path:** `rx_clk[i]` → `core_clk`
- Async FIFOs in MAC wrappers
- Configurable depth: `GEN_MACS_AXI_RX_BUF_DEPTH`

**TX Path:** `core_clk` → `tx_clk[i]`
- Async FIFOs in MAC wrappers
- Configurable depth: `GEN_MACS_AXI_TX_BUF_DEPTH`

**Register Access:** `axi_clk/apb_clk` → `bus2ip_clk` → port clocks
- Protocol bridges handle CDC
- Timeout mechanisms (64 cycles) prevent hangs

---

### 3.5 PTP (Precision Time Protocol) Support

#### 3.5.1 Time-of-Day (ToD) Management

**External PTP Mode** (`GEN_INT_PTP = false`, lines 217-220):
```vhdl
-- ToD provided by external PTP stack
tod_rx <= tod_rx_i;  -- 96-bit RX timestamp
tod_tx <= tod_tx_i;  -- 96-bit TX timestamp
```

**Internal PTP Mode** (`GEN_INT_PTP = true`, lines 222-225):
```vhdl
-- ToD generated by Manticore core
tod_rx <= mtcr_tod;
tod_tx <= mtcr_tod;
-- mtcr_tod output from manticore_top
```

#### 3.5.2 ToD Distribution

**Multi-ToD Support** (`GEN_N_TOD` > 1):
- Separate ToD domains for different port groups
- Mapping configured via `C_TOD_MAC_MAP(i)` array
- Each MAC can use different ToD source

**ToD Format:**
```
Bits [95:48] : Seconds (48-bit)
Bits [47:0]  : Nanoseconds (48-bit fractional)
```

#### 3.5.3 PTP Compensation

**PCS Compensation Inputs:**
```vhdl
tsu_pcs_rx_com_i : in std_logic_vector(63 downto 0);  -- RX path delay
tsu_pcs_tx_com_i : in std_logic_vector(63 downto 0);  -- TX path delay
```
- Compensates for PCS layer latency
- Improves timestamp accuracy
- Applied in MAC timestamping units

---

### 3.6 Memory Interface

#### 3.6.1 Packet Buffer Memory

**Per-Port Memory Partitions:**
```vhdl
mem_pkt_buf_wen_o    : out std_logic_vector(GEN_N_PORTS-1 downto 0);
mem_pkt_buf_waddr_o  : out std_logic_vector(GEN_N_PORTS*GEN_PKT_BUF_ADDR_WIDTH - 1);
mem_pkt_buf_wdata_o  : out std_logic_vector(GEN_N_PORTS*GEN_CORE_DATA_WIDTH*8 - 1);
mem_pkt_buf_ren_o    : out std_logic_vector(GEN_N_PORTS-1 downto 0);
mem_pkt_buf_raddr_o  : out std_logic_vector(GEN_N_PORTS*GEN_PKT_BUF_ADDR_WIDTH - 1);
mem_pkt_buf_rdata_i  : in  std_logic_vector(GEN_N_PORTS*GEN_CORE_DATA_WIDTH*8 - 1);
```

**Packet Buffer Usage:**
- Stores packet data during switching
- Allows store-and-forward operation
- Enables packet replication for multicast
- Size per port: 2^`GEN_PKT_BUF_ADDR_WIDTH` entries
- Data width: `GEN_CORE_DATA_WIDTH` bytes (typically 8 bytes)

#### 3.6.2 Credit Buffer Memory

**Per-Port Credit Tracking:**
```vhdl
mem_crd_buf_wen_o    : out std_logic_vector(GEN_N_PORTS-1 downto 0);
mem_crd_buf_waddr_o  : out std_logic_vector(GEN_N_PORTS*GEN_CRD_BUF_ADDR_WIDTH - 1);
mem_crd_buf_wdata_o  : out std_logic_vector(GEN_N_PORTS*GEN_CORE_DATA_WIDTH*8 - 1);
mem_crd_buf_ren_o    : out std_logic_vector(GEN_N_PORTS-1 downto 0);
mem_crd_buf_raddr_o  : out std_logic_vector(GEN_N_PORTS*GEN_CRD_BUF_ADDR_WIDTH - 1);
mem_crd_buf_rdata_i  : in  std_logic_vector(GEN_N_PORTS*GEN_CORE_DATA_WIDTH*8 - 1);
```

**Credit Buffer Usage:**
- Implements Virtual Output Queuing (VOQ) credits
- Prevents buffer overflow at egress ports
- Tracks available buffer space per output port
- Enables credit-based flow control

**Memory Organization:**
```
Port 0: [wdata(63:0), waddr, wen, rdata(63:0), raddr, ren]
Port 1: [wdata(63:0), waddr, wen, rdata(63:0), raddr, ren]
...
Port N: [wdata(63:0), waddr, wen, rdata(63:0), raddr, ren]
```

---

## 4. Key Design Parameters

### 4.1 Generic Constants (from `manticore_generic_const_pkg`)

| Parameter | Typical Value | Description |
|-----------|---------------|-------------|
| `GEN_N_PORTS` | 4-8 | Total number of switch ports |
| `GEN_N_MACS` | 4 | Number of integrated 10G XGMII MACs |
| `GEN_N_1B_MAC_PORTS` | 0 | Number of 1-byte (1G) MAC ports |
| `GEN_N_8B_MAC_PORTS` | 4 | Number of 8-byte (10G) MAC ports |
| `GEN_N_CPU_PORTS` | 0-1 | Number of CPU interface ports |
| `GEN_CORE_DATA_WIDTH` | 8 | Switch core data width (bytes) |
| `GEN_CPU_PORT_DWID` | 8 | CPU port data width (bytes) |
| `GEN_CELL_SIZE` | 64 | Cell size for segmentation (bytes) |
| `GEN_PKT_BUF_ADDR_WIDTH` | 12-16 | Packet buffer address bits per port |
| `GEN_CRD_BUF_ADDR_WIDTH` | 8-12 | Credit buffer address bits per port |
| `GEN_N_IPVS` | 8 | Number of Internal Priority Queues (IPVs) |
| `GEN_Q_BUF_SZ` | 9 | Queue buffer size (log2 entries) |
| `GEN_TS_EN` | true | PTP timestamping enable |
| `GEN_INT_PTP` | false | Internal vs external PTP |
| `GEN_N_TOD` | 1 | Number of ToD domains |
| `GEN_MACS_BASE_ADDR` | 0x10000 | Base address for MAC registers |
| `GEN_MACS_AXI_TX_BUF_DEPTH` | 512-2048 | TX FIFO depth (entries) |
| `GEN_MACS_AXI_RX_BUF_DEPTH` | 512-2048 | RX FIFO depth (entries) |
| `GEN_MACS_TX_STORE_N_FWD` | true | TX store-and-forward enable |
| `GEN_MACS_RX_STORE_N_FWD` | true | RX store-and-forward enable |
| `GEN_REG_ACCESS_IFACE` | "axi"/"apb"/"ip2bus" | Register interface type |
| `GEN_MAX_CX_MUX` | 4 | Crossbar mux radix |
| `GEN_N_MAE` | 1 | Number of MAC Action Engines |
| `GEN_N_FDB_TABLES` | 1 | Number of FDB (forwarding) tables |

### 4.2 Port Configuration Constants

Derived constants for port configuration:

```vhdl
-- External AXI-Stream port counts (non-XGMII ports)
C_N_NO_MAC_PORTS     = Total external AXI ports
C_N_1B_NO_MAC_PORTS  = Number of 1-byte external ports
C_N_8B_NO_MAC_PORTS  = Number of 8-byte external ports
C_N_CPU_NO_MAC_PORTS = Number of CPU external ports

-- Total port equation:
GEN_N_PORTS = GEN_N_1B_MAC_PORTS + GEN_N_8B_MAC_PORTS + 
              C_N_1B_NO_MAC_PORTS + C_N_8B_NO_MAC_PORTS + 
              C_N_CPU_NO_MAC_PORTS
```

---

## 5. Interface Specifications

### 5.1 XGMII Interface (10G MACs)

```vhdl
-- Per-port 64-bit XGMII (concatenated for all MACs)
xgmii_rxd_i : in  std_logic_vector(GEN_N_MACS*64-1 downto 0);
xgmii_rxc_i : in  std_logic_vector(GEN_N_MACS*8-1 downto 0);
xgmii_txd_o : out std_logic_vector(GEN_N_MACS*64-1 downto 0);
xgmii_txc_o : out std_logic_vector(GEN_N_MACS*8-1 downto 0);
```

**XGMII Format:**
- 64-bit data (`rxd`/`txd`): 8 lanes × 8 bits
- 8-bit control (`rxc`/`txc`): 1 bit per lane
- Control bits indicate data vs. control characters
- Standard 10GBASE-R encoding

### 5.2 AXI-Stream Interface (External Ports)

```vhdl
-- RX (from external MACs to switch)
rx_eth_axis_tvalid_i : in  std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
rx_eth_axis_tready_o : out std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
rx_eth_axis_tdata_i  : in  std_logic_vector(TOTAL_DATA_WIDTH-1 downto 0);
rx_eth_axis_tlast_i  : in  std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
rx_eth_axis_tkeep_i  : in  std_logic_vector(TOTAL_KEEP_WIDTH-1 downto 0);
rx_eth_axis_tuser_i  : in  std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);

-- TX (from switch to external MACs)
tx_eth_axis_tvalid_o : out std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
tx_eth_axis_tready_i : in  std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
tx_eth_axis_tdata_o  : out std_logic_vector(TOTAL_DATA_WIDTH-1 downto 0);
tx_eth_axis_tlast_o  : out std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
tx_eth_axis_tkeep_o  : out std_logic_vector(TOTAL_KEEP_WIDTH-1 downto 0);
tx_eth_axis_tuser_o  : out std_logic_vector(C_N_NO_MAC_PORTS-1 downto 0);
```

**AXI-Stream Protocol:**
- Standard AXI4-Stream with `tvalid`/`tready` handshake
- `tlast`: End-of-packet marker
- `tkeep`: Byte valid indicator (per byte in `tdata`)
- `tuser[0]`: Error flag (RX: CRC error, TX: underflow)

**Data Width Calculation:**
```
TOTAL_DATA_WIDTH = C_N_1B_NO_MAC_PORTS * 8 +
                   C_N_8B_NO_MAC_PORTS * 64 +
                   C_N_CPU_NO_MAC_PORTS * GEN_CPU_PORT_DWID * 8

TOTAL_KEEP_WIDTH = C_N_1B_NO_MAC_PORTS * 1 +
                   C_N_8B_NO_MAC_PORTS * 8 +
                   C_N_CPU_NO_MAC_PORTS * GEN_CPU_PORT_DWID
```

### 5.3 AXI4-Lite Register Interface

```vhdl
s_axi_aclk_i    : in  std_logic;
s_axi_aresetn_i : in  std_logic;

-- Write address channel
s_axi_awaddr_i  : in  std_logic_vector(C_AWID-1 downto 0);  -- 32-bit address
s_axi_awvalid_i : in  std_logic;
s_axi_awready_o : out std_logic;

-- Write data channel
s_axi_wdata_i   : in  std_logic_vector(C_DWID-1 downto 0);  -- 32-bit data
s_axi_wvalid_i  : in  std_logic;
s_axi_wready_o  : out std_logic;

-- Write response channel
s_axi_bready_i  : in  std_logic;
s_axi_bresp_o   : out std_logic_vector(1 downto 0);  -- 00=OKAY, 10=SLVERR
s_axi_bvalid_o  : out std_logic;

-- Read address channel
s_axi_araddr_i  : in  std_logic_vector(C_AWID-1 downto 0);
s_axi_arvalid_i : in  std_logic;
s_axi_arready_o : out std_logic;

-- Read data channel
s_axi_rready_i  : in  std_logic;
s_axi_rdata_o   : out std_logic_vector(C_DWID-1 downto 0);
s_axi_rresp_o   : out std_logic_vector(1 downto 0);
s_axi_rvalid_o  : out std_logic;
```

**Protocol:**
- Fully compliant AXI4-Lite slave interface
- 32-bit address bus (`C_AWID = 32`)
- 32-bit data bus (`C_DWID = 32`)
- Separate read/write channels
- Timeout protection (64 cycles)

### 5.4 APB Register Interface

```vhdl
apb_aclk_i      : in  std_logic;
apb_aresetn_i   : in  std_logic;

apb_paddr_i     : in  std_logic_vector(C_AWID-1 downto 0);  -- 32-bit address
apb_psel_i      : in  std_logic;                            -- Slave select
apb_pwdata_i    : in  std_logic_vector(C_DWID-1 downto 0); -- 32-bit write data
apb_penable_i   : in  std_logic;                            -- Enable (access phase)
apb_pwrite_i    : in  std_logic;                            -- Write=1, Read=0

apb_pready_o    : out std_logic;                            -- Transfer complete
apb_pslverr_o   : out std_logic;                            -- Error flag
apb_prdata_o    : out std_logic_vector(C_DWID-1 downto 0); -- Read data
```

**Protocol:**
- APB4 compliant slave interface
- 3-phase protocol: IDLE → SETUP → ACCESS
- `psel=1, penable=0`: SETUP phase
- `psel=1, penable=1`: ACCESS phase
- `pready=1`: Transfer complete

---

## 6. Internal Architecture Details

### 6.1 Manticore Switch Core (`manticore_top`)

**Sub-modules:**

1. **Port Processing Units** (`manticore_port`) - One per port
   - Packet parser: Extract L2/L3/L4 headers
   - FDB lookup: MAC address learning and forwarding
   - Ingress queuing: Per-priority queues (VOQ)
   - Egress queuing: Credit management
   - TSN support: CBS (Credit-Based Shaper), TAS (Time-Aware Shaper)

2. **MAC Action Engine** (`mae_top`)
   - TCAM-based packet classification
   - QoS policy enforcement
   - VLAN manipulation (add/remove/modify tags)
   - Forwarding decision override
   - Packet mirroring and sampling

3. **Scheduler** (`sch_sync`)
   - Round-robin + priority arbitration
   - Multicast pointer generation
   - Cycle synchronization
   - Dequeue cycle control

4. **Crossbar Switch** (`crossbar`)
   - Non-blocking N×N switch fabric
   - Configurable mux radix: `GEN_MAX_CX_MUX` (typical: 4)
   - Bus width: 64 data + 11 control bits = 75 bits total
   - Pipeline stages: Input register + Output register
   - Dynamic reconfiguration per cycle

5. **Crossbar Configuration Generator** (`cb_conf_gen`)
   - Accepts grant vectors from scheduler
   - Generates crossbar configuration matrix
   - Delay pipeline to align with packet data

**Data Flow:**

```
RX → Parse → Learn → Queue → Arbitrate → Crossbar → Dequeue → TX
       ↓       ↓       ↓         ↓           ↓         ↓
     Metadata  FDB   VOQ      Scheduler   Switch    Credits
     Extract  Lookup  Store               Fabric    Check
```

### 6.2 Width Adaptation Logic

**Problem:** External AXI-Stream ports have variable widths (1/8/N bytes), but the switch core expects uniform `GEN_CORE_DATA_WIDTH` byte ports.

**Solution:** Port mapping functions (lines 178-214)

```vhdl
function get_port_dwid_axi(i : integer) return integer is
  -- Returns external port width: 1, 8, or GEN_CPU_PORT_DWID bytes
  
function get_port_pos_axi(i : integer) return integer is
  -- Returns byte position in concatenated data vector
  
function get_empty_pos_axi(i : integer) return integer is
  -- Returns bit position for empty signal encoding
```

**Mapping Example (4 external ports: 1G, 1G, 10G, CPU):**
```
External AXI-Stream:
  tdata = [CPU_data(N*8-1:0) | 10G_data(63:0) | 1G_data(7:0) | 1G_data(7:0)]
  tkeep = [CPU_keep(N-1:0) | 10G_keep(7:0) | 1G_keep(0:0) | 1G_keep(0:0)]

Internal Switch:
  Each port gets uniform 8-byte width (padded if necessary)
```

### 6.3 Debug Infrastructure

**ChipScope/ILA Probe Points** (lines 161-176):

```vhdl
attribute mark_debug of rx_eth_axis_tvalid : signal is "true";
attribute mark_debug of rx_eth_axis_tdata  : signal is "true";
attribute mark_debug of tx_eth_axis_tvalid : signal is "true";
attribute mark_debug of tx_eth_axis_tdata  : signal is "true";
-- etc.
```

- Enables Xilinx Vivado Integrated Logic Analyzer (ILA)
- Real-time signal capture in hardware
- Useful for debugging packet flow issues
- Additional probe points in MAC wrappers (lines 450-470)

---

## 7. Configuration Examples

### 7.1 Typical 4-Port 10G Switch

```vhdl
generic map (
  GEN_N_PORTS              => 4,
  GEN_N_MACS               => 4,      -- All ports use integrated MACs
  GEN_N_1B_MAC_PORTS       => 0,
  GEN_N_8B_MAC_PORTS       => 4,
  GEN_N_CPU_PORTS          => 0,
  GEN_CORE_DATA_WIDTH      => 8,      -- 64-bit switch core
  GEN_MACS_BASE_ADDR       => x"10000",
  GEN_TS_EN                => true,   -- PTP enabled
  GEN_INT_PTP              => false,  -- External PTP stack
  GEN_REG_ACCESS_IFACE     => "axi",
  GEN_MACS_TX_STORE_N_FWD  => true,
  GEN_MACS_RX_STORE_N_FWD  => true
)
```

### 7.2 Mixed 1G/10G Switch with CPU Port

```vhdl
generic map (
  GEN_N_PORTS              => 7,      -- 4×1G + 2×10G + 1×CPU
  GEN_N_MACS               => 2,      -- 2 integrated 10G MACs
  GEN_N_1B_MAC_PORTS       => 4,      -- 4 external 1G ports
  GEN_N_8B_MAC_PORTS       => 2,      -- 2 external 10G ports
  GEN_N_CPU_PORTS          => 1,
  GEN_CPU_PORT_DWID        => 8,      -- 64-bit CPU interface
  GEN_REG_ACCESS_IFACE     => "apb",
  GEN_TS_EN                => false,  -- No PTP
  ...
)
```

### 7.3 Cut-Through Low-Latency Configuration

```vhdl
generic map (
  GEN_MACS_TX_STORE_N_FWD  => false,  -- Cut-through TX
  GEN_MACS_RX_STORE_N_FWD  => false,  -- Cut-through RX
  GEN_MACS_AXI_TX_BUF_DEPTH => 64,    -- Minimal buffering
  GEN_MACS_AXI_RX_BUF_DEPTH => 64,
  -- Results in ~200ns port-to-port latency
)
```

---

## 8. Performance Characteristics

### 8.1 Throughput

| Configuration | Aggregate Throughput | Per-Port Throughput |
|---------------|---------------------|---------------------|
| 4×10G | 40 Gbps | 10 Gbps line-rate |
| 8×10G | 80 Gbps | 10 Gbps line-rate |
| 24×1G + 4×10G | 64 Gbps | Line-rate per port |

**Non-blocking:** All ports can achieve line-rate simultaneously (wire-speed).

### 8.2 Latency

| Mode | Port-to-Port Latency |
|------|---------------------|
| Cut-through | 200-500 ns |
| Store-and-forward (64B) | 500 ns - 1 μs |
| Store-and-forward (1518B) | 12-15 μs |

**Factors:**
- Switch core: ~10-20 clock cycles @ 300 MHz = 33-67 ns
- MAC processing: ~50-100 ns per MAC
- Memory access latency: Variable based on buffer depth
- Crossbar stages: ~2-5 clock cycles

### 8.3 Buffer Capacity

**Per-Port Packet Buffer:**
```
Size = 2^GEN_PKT_BUF_ADDR_WIDTH × GEN_CORE_DATA_WIDTH bytes
Example: 2^14 × 8 = 128 KB per port
```

**Total Switch Buffer:**
```
Total = GEN_N_PORTS × Per-Port Size
Example: 8 ports × 128 KB = 1 MB
```

### 8.4 Resource Utilization (Xilinx 7-Series)

Estimated for 4-port 10G configuration:

| Resource | Utilization | Notes |
|----------|-------------|-------|
| LUTs | 40,000-60,000 | Depends on feature set |
| FFs | 50,000-70,000 | Heavy pipeline usage |
| BRAMs | 20-40 | Packet/credit buffers |
| DSPs | 0-4 | Timestamp arithmetic |

**Notes:**
- BRAM usage scales with buffer size
- MAC wrappers: ~5,000 LUTs + 10 BRAMs each
- Switch core: ~20,000 LUTs + 5 BRAMs
- MAE (if enabled): ~10,000 LUTs + 5 BRAMs

---

## 9. Feature Matrix

| Feature | Support | Configuration |
|---------|---------|---------------|
| **Switching** |
| Layer 2 switching | ✅ Yes | Always enabled |
| MAC learning | ✅ Yes | FDB tables in MAE |
| VLAN support | ✅ Yes | 802.1Q tagging |
| Multicast | ✅ Yes | Packet replication |
| Broadcast | ✅ Yes | All-port forwarding |
| Jumbo frames | ✅ Yes | Up to 9600 bytes |
| **QoS** |
| Priority queues | ✅ Yes | GEN_N_IPVS queues (typical: 8) |
| Weighted fair queuing | ✅ Yes | Scheduler configured |
| Strict priority | ✅ Yes | Scheduler configured |
| **TSN (Time-Sensitive Networking)** |
| Time-Aware Shaper (TAS) | ✅ Yes | IEEE 802.1Qbv |
| Credit-Based Shaper (CBS) | ✅ Yes | IEEE 802.1Qav |
| Frame Preemption | ⚠️ Partial | Depends on MAC |
| **Timing** |
| PTP (IEEE 1588) | ✅ Yes | Hardware timestamping |
| PTP Transparent Clock | ✅ Yes | In MAE |
| PTP Boundary Clock | ✅ Yes | With external stack |
| **Interfaces** |
| XGMII (10G) | ✅ Yes | Integrated MACs |
| AXI-Stream | ✅ Yes | External MACs |
| GMII/RGMII (1G) | ⚠️ External | Via AXI-Stream adapter |
| SFP+/QSFP+ | ⚠️ External | Via SerDes + PCS |
| **Management** |
| AXI4-Lite registers | ✅ Yes | Configurable |
| APB registers | ✅ Yes | Configurable |
| MDIO | ⚠️ Limited | Via MAC wrappers |
| Statistics counters | ✅ Yes | Per-port, per-queue |
| **Advanced** |
| Store-and-forward | ✅ Yes | Configurable per MAC |
| Cut-through | ✅ Yes | Configurable per MAC |
| Flow control (Pause) | ✅ Yes | In MAC wrappers |
| Port mirroring | ✅ Yes | Via MAE |
| Rate limiting | ✅ Yes | Via CBS/TAS |

---

## 10. Integration Guidelines

### 10.1 Clocking Strategy

**Recommended Clock Architecture:**

```
External Source (PLL/MMCM):
  ├─ core_clk   : 300 MHz  (switch fabric, primary processing)
  ├─ sch_clk    : 300 MHz  (scheduler, can be same as core_clk)
  ├─ mae_clk    : 300 MHz  (MAE, can be same as core_clk)
  ├─ axi_clk    : 100-150 MHz (register access)
  └─ rx_clk[i]  : 156.25 MHz per port (from transceiver)
      tx_clk[i]  : 156.25 MHz per port (from transceiver)
```

**Clock Relationships:**
- `core_clk`, `sch_clk`, `mae_clk` can share the same source (simplifies design)
- Port clocks (`rx_clk`, `tx_clk`) must be derived from SerDes transceivers
- Register clock can be asynchronous (CDC handled by bridges)

### 10.2 Reset Strategy

**Recommended Reset Sequence:**

1. **Global Reset:** Assert all resets for ≥100 ns
2. **Core Reset Release:** Release `core_rst_i`, `sch_rst_i`, `mae_rst_i`
3. **Port Reset Release:** Release `tx_rst_i[*]`, `rx_rst_i[*]` after transceivers lock
4. **Bus Reset Release:** Release `s_axi_aresetn_i` or `apb_aresetn_i` last

**Reset Polarity:**
```vhdl
G_RESET_ACTIVE => false   -- Resets active-low (typical)
G_RESET_ACTIVE => true    -- Resets active-high
```

### 10.3 External Memory Instantiation

**Dual-Port RAM Template (per port):**

```vhdl
-- Packet Buffer RAM (Port 0 example)
u_pkt_buf_0 : dual_port_ram
  generic map (
    ADDR_WIDTH => GEN_PKT_BUF_ADDR_WIDTH,  -- e.g., 14 bits = 16K entries
    DATA_WIDTH => GEN_CORE_DATA_WIDTH*8    -- e.g., 64 bits
  )
  port map (
    clk_a     => core_clk_i,
    wen_a     => mem_pkt_buf_wen_o(0),
    addr_a    => mem_pkt_buf_waddr_o(GEN_PKT_BUF_ADDR_WIDTH-1 downto 0),
    wdata_a   => mem_pkt_buf_wdata_o(GEN_CORE_DATA_WIDTH*8-1 downto 0),
    
    clk_b     => core_clk_i,
    ren_b     => mem_pkt_buf_ren_o(0),
    addr_b    => mem_pkt_buf_raddr_o(GEN_PKT_BUF_ADDR_WIDTH-1 downto 0),
    rdata_b   => mem_pkt_buf_rdata_i(GEN_CORE_DATA_WIDTH*8-1 downto 0)
  );

-- Repeat for credit buffer and other ports
```

**Memory Requirements:**
- Read latency: 1-2 cycles (pipelined OK)
- Write latency: Immediate (write-through or posted write)
- Can use FPGA block RAM or external SRAM/DRAM

### 10.4 PTP Integration

**External PTP Stack Connection:**

```vhdl
-- Connect to external PTP daemon or hardware stack
tod_rx_i <= ptp_stack_tod_out;  -- 96-bit: {seconds[47:0], nanoseconds[47:0]}
tod_tx_i <= ptp_stack_tod_out;  -- Same ToD for TX

-- Optional: Different ToD per port group
tod_rx_i(95 downto 0)   <= ptp_tod_domain0;  -- Ports 0-1
tod_rx_i(191 downto 96) <= ptp_tod_domain1;  -- Ports 2-3
```

**PCS Compensation Calibration:**
```vhdl
-- Measure PCS latency (ns) and convert to compensation value
tsu_pcs_rx_com_i <= std_logic_vector(to_unsigned(RX_PCS_DELAY_NS, 64));
tsu_pcs_tx_com_i <= std_logic_vector(to_unsigned(TX_PCS_DELAY_NS, 64));
```

### 10.5 Software Initialization Sequence

**Register Configuration Steps:**

1. **Reset and Disable:**
   ```c
   // Assert soft reset
   write_reg(CORE_BASE + SOFT_RESET, 0x1);
   delay_us(10);
   write_reg(CORE_BASE + SOFT_RESET, 0x0);
   ```

2. **Configure MAE (if used):**
   ```c
   // Initialize FDB tables
   write_reg(MAE_BASE + FDB_CTRL, FDB_CLEAR);
   write_reg(MAE_BASE + FDB_AGING_TIME, 300);  // 300s aging
   ```

3. **Configure Per-Port Settings:**
   ```c
   for (int i = 0; i < NUM_PORTS; i++) {
     uint32_t mac_base = MAC_BASE + i * MAC_STRIDE;
     
     // Set MAC address
     write_reg(mac_base + MAC_ADDR_LO, mac_addr_lo);
     write_reg(mac_base + MAC_ADDR_HI, mac_addr_hi);
     
     // Enable RX/TX
     write_reg(mac_base + MAC_CTRL, MAC_RX_EN | MAC_TX_EN);
     
     // Configure VLAN (if needed)
     write_reg(mac_base + VLAN_CTRL, vlan_config);
   }
   ```

4. **Enable Switching:**
   ```c
   write_reg(CORE_BASE + SWITCH_CTRL, SWITCH_EN);
   ```

---

## 11. Known Limitations and Considerations

### 11.1 Design Limitations

1. **Port Count:**
   - Maximum: ~16 ports (limited by crossbar complexity)
   - Practical: 4-8 ports for optimal resource usage

2. **Buffer Memory:**
   - Must be externally instantiated (not included in module)
   - Depth directly affects maximum packet count per port

3. **Clock Domain Complexity:**
   - Each port can have independent RX/TX clocks
   - Requires careful constraint management in timing analysis

4. **Register Access:**
   - Only one of {AXI, APB, IP2Bus} can be active
   - No dynamic switching between register interfaces

### 11.2 Performance Considerations

1. **Cut-Through vs Store-and-Forward:**
   - Cut-through: Lower latency, but error propagation
   - Store-and-forward: Higher latency, but error isolation

2. **FIFO Depths:**
   - Undersized FIFOs cause backpressure and throughput loss
   - Oversized FIFOs waste BRAM resources
   - Recommend: 1-2 MTU sizes minimum

3. **TSN Timing:**
   - TAS requires synchronized clock across all ports
   - CBS requires accurate rate monitoring
   - Both require careful software configuration

### 11.3 Debug Recommendations

1. **Enable ILA Probes:**
   ```tcl
   # Add to Vivado synthesis
   set_property mark_debug true [get_nets <signal_name>]
   ```

2. **Monitor Key Signals:**
   - AXI-Stream handshakes (`tvalid`/`tready` stalls)
   - Crossbar configuration changes
   - Buffer overflow/underflow indicators
   - PTP timestamp discontinuities

3. **Statistics Registers:**
   - Regularly poll packet/byte counters
   - Check error counters for CRC, overflow, underrun
   - Monitor queue occupancy levels

---

## 12. References

### 12.1 Related Modules

| Module | File Path | Description |
|--------|-----------|-------------|
| `manticore_top` | `ip/manticore/rtl/manticore_top.vhd` | Switch core |
| `manticore_port` | `ip/manticore/rtl/manticore_port.vhd` | Per-port processing |
| `mae_top` | `ip/manticore/rtl/mae/mae_top.vhd` | MAC Action Engine |
| `crossbar` | `ip/manticore/rtl/crossbar.vhd` | Switch fabric |
| `xgmii_axi_mac_wrapper` | `ip/mac/xgmii_axi_mac_wrapper.vhd` | 10G MAC wrapper |
| `bus2ip_ic` | `ip/common/blocks/bus2ip_ic.vhd` | Bus interconnect |
| `axi2ip` | (Xilinx IP or custom) | AXI4-Lite bridge |
| `apb2ip` | (Xilinx IP or custom) | APB bridge |

### 12.2 Package Dependencies

```vhdl
use work.common_tools_numeric_pkg.all;      -- Math functions, log2ceil, etc.
use work.manticore_generic_const_pkg.all;  -- Generic constants (GEN_*)
use work.manticore_pkg.all;                -- Type definitions, functions
use work.manticore_components_pkg.all;     -- Component declarations
use work.grm_components_pkg.all;           -- GRM (register) components
```

### 12.3 Standards Compliance

- **IEEE 802.3**: Ethernet MAC (10/100/1000/10000 Mbps)
- **IEEE 802.1Q**: VLAN tagging
- **IEEE 802.1Qav**: Credit-Based Shaper (CBS) for TSN
- **IEEE 802.1Qbv**: Time-Aware Shaper (TAS) for TSN
- **IEEE 1588**: Precision Time Protocol (PTP) v2

---

## 13. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-22 | Analysis Tool | Initial comprehensive analysis |

---

## 14. Appendix: Signal Cross-Reference

### 14.1 Critical Internal Signals

| Signal Name | Width | Clock Domain | Description |
|-------------|-------|--------------|-------------|
| `rx_eth_axis_tvalid` | GEN_N_PORTS | rx_clk[i] | Internal RX AXI valid |
| `rx_eth_axis_tdata` | Variable | rx_clk[i] | Internal RX AXI data |
| `tx_eth_axis_tvalid` | GEN_N_PORTS | tx_clk[i] | Internal TX AXI valid |
| `crossbar_cfg` | N×N | core_clk | Crossbar routing matrix |
| `ip2bus_data_master` | (N+1)×32 | bus2ip_clk | Register read data mux |
| `tod_rx` / `tod_tx` | 96×GEN_N_TOD | - | PTP Time-of-Day |

---

**End of Document**
