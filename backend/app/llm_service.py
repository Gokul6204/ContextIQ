from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import List, Dict
import os

class LLMService:
    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        # User provided Groq API key
        self.api_key = os.getenv("GROQ_API_KEY")
        
        self.llm = ChatGroq(
            groq_api_key=self.api_key,
            model_name=model_name,
            temperature=0.1,
            max_tokens=2048, # Increased for detailed research answers
            timeout=60 # Increased for stability on long generations
        )
        self.prompt_template = ChatPromptTemplate.from_template("""
            You are Antigravity, an advanced analytical AI research assistant inspired by NotebookLM.

            Your goal is to provide precise, structured, and context-grounded answers.

            CRITICAL RULES:
            1. Try your best to answer the question using the provided Context.
            2. If the Context doesn't contain the exact keywords, look for conceptually related information and use it.
            3. You may use your general knowledge to supplement the answer and provide a rich response, but always prioritize what is in the Context.
            4. If the Context is completely irrelevant or empty, answer the question anyway based on your general knowledge, but politely mention that the provided documents don't specifically cover it.
            5. Be as helpful and conversational as possible. Maintain a professional tone.

            SPECIAL INSTRUCTION FOR COMPARISON QUESTIONS:
            If the question includes words like:
            - difference
            - compare
            - vs / versus
            - advantages
            - disadvantages
            - similarities
            - pros and cons

            Then structure your answer as follows:

            Step 1: Brief explanation of each concept individually (based strictly on Context).
            Step 2: Clear comparison using bullet points.
            Step 3: Short summary highlighting the key distinctions.

            For non-comparison questions:
            Provide a clear, well-structured explanation using bullet points if helpful.

            If metadata like filenames or page numbers are available in the context, cite them clearly.

            Context:
            ---------------------
            {context}
            ---------------------

            Question:
            {question}

            Structured Answer:
            """)

    async def generate_response(self, question: str, context: str) -> str:
        chain = self.prompt_template | self.llm | StrOutputParser()
        response = await chain.ainvoke({"question": question, "context": context})
        return response
