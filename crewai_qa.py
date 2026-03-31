import os
from crewai import Agent, Task, Crew
from crewai.llm import LLM

os.environ["OPENAI_API_KEY"] = "sk-cp-***"
os.environ["OPENAI_API_BASE"] = "https://cloud.infini-ai.com/maas/coding/v1"

llm = LLM(model="openai/kimi-k2.5", temperature=0.7)

agent = Agent(
    role="问答助手",
    goal="提供准确、有帮助的回答",
    backstory="你是一个专业的问答助手，擅长用简洁清晰的语言回答用户问题",
    llm=llm,
)

task = Task(
    description="回答用户的问题：什么是CrewAI？",
    expected_output="一段关于CrewAI的详细介绍",
    agent=agent,
)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()
print(result)
