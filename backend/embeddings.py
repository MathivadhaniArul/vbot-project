from langchain_text_splitters import MarkdownHeaderTextSplitter
from dotenv import load_dotenv
import os
import pinecone

load_dotenv()
pinecone_api_key = os.getenv("PINECONE_API_KEY")

# Chunk the document based on h2 headers.
#markdown_document ="5 Absolute and Relative GradingThe letter grade awarded to a student for his/her performance in a course can be based on eitherthe Absolute Grading or the Relative Grading concept.The ‘Relative Grading’ concept indicates the academic standing of a student in his/her class. All thetheory component of the courses, with the class strength is more than 10, shall follow class-wiserelative grading concept. In Relative Grading, the following two extreme situations which normallyupset the students are nullified1. Majority of students scoring very high marks because, either the question paper is easy orthe evaluator is very lenient.2. Majority of students scoring very low marks because of either the question paper istough or the evaluator is very strict.In this system, grades are awarded to students according to their performance relative to their peersin the same class (class is defined as a unique combination of course-slot-faculty). Normally the classaverage mark is taken as midpoint of ‘B’ grade, and relative to this and depending on the sigma (σ,standard deviation) value, the other grades are finalized as given in Table-5. A combination ofabsolute and relative grading systems is adopted in converting marks to gradesIf the class strength is less than or equal to 10 in a theory or lab embedded theory course absolutegrading shall be adopted instead of the class-wise relative grading. All the Laboratory, soft skills,extracurricular, non-graded core requirement (NGCR) courses and project courses shall adoptabsolute grading method only, irrespective of the class strength as shown in Table-6."
with open("regulations.md", "r", encoding="utf-8") as f:
    markdown_document = f.read()

headers_to_split_on = [
    ("###", "Header 2")
]

markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on, strip_headers=False
)
md_header_splits = markdown_splitter.split_text(markdown_document)

# print(md_header_splits)
# print("\n")
#from langchain_pinecone import PineconeEmbeddings
import os

from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=os.environ.get("OPENAI_API_KEY")
)

from pinecone import Pinecone, ServerlessSpec
import time

pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

cloud = os.environ.get('PINECONE_CLOUD') or 'aws'
region = os.environ.get('PINECONE_REGION') or 'us-east-1'
spec = ServerlessSpec(cloud=cloud, region=region)

index_name = "rag-getting-started"

pc.delete_index(index_name)
pc.create_index(
    name=index_name,
    dimension=1536,   # match your new embedding model
    metric="cosine",
    spec=spec
)

# See that it is empty
# print("Index before upsert:")
# print(pc.Index(index_name).describe_index_stats())
# print("\n")
from langchain_pinecone import PineconeVectorStore

namespace = "wondervector5000"

docsearch = PineconeVectorStore.from_documents(
    documents=md_header_splits,
    index_name=index_name,
    embedding=embeddings,
    namespace=namespace
)

time.sleep(5)

# See how many vectors have been upserted
# print("Index after upsert:")
# print(pc.Index(index_name).describe_index_stats())
# print("\n")
# time.sleep(2)
index = pc.Index(index_name)
namespace = "wondervector5000"

for ids in index.list(namespace="wondervector5000"):
    query = index.query(
        id=ids[0], 
        namespace="wondervector5000", 
        top_k=3,
        include_values=True,
        include_metadata=True
    )
    # print(query)
    # print("\n")
    from langchain_openai import ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain import hub
from langchain_openai import ChatOpenAI

retrieval_qa_chat_prompt = hub.pull("langchain-ai/retrieval-qa-chat")
retriever = docsearch.as_retriever(search_kwargs={"namespace": "wondervector5000"})


llm = ChatOpenAI(
    openai_api_key=os.environ.get('OPENAI_API_KEY'),
    model_name='gpt-4o-mini',
    temperature=0.0
)

combine_docs_chain = create_stuff_documents_chain(
    llm, retrieval_qa_chat_prompt
)
retrieval_chain = create_retrieval_chain(retriever, combine_docs_chain)
#query1 = "what is the re-evaluation procedure?"

query2 = "what is the minimum class strength for absolute grading?"

#print(pc.Index(index_name).describe_index_stats())
# for i, doc in enumerate(md_header_splits):
#     print(f"\n--- Document {i+1} ---")
#     print(doc.page_content[:500])






# print("Answer with knowledge:\n\n", answer1_with_knowledge['answer'])
# print("\nContext used:\n\n", answer1_with_knowledge['context'])
# print("\n")

import streamlit as st

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "Hello! How can I help you?"}]
   
#st.markdown(f"Your selected options: {selection}.")
options = ["what is the minimum class strength for absolute grading?", "what is the re-evaluation procedure?", "what is the minimum credits we can register during FFCS"]
selection = st.pills("FAQ", options, selection_mode="single")
# Display chat history
if "last_selection" not in st.session_state:
    st.session_state["last_selection"] = None
if selection and selection != st.session_state["last_selection"]:
    with st.spinner("AI is thinking..."):
        st.session_state["last_selection"] = selection
        st.session_state.messages.append({"role": "user", "content": selection })
    # Here, call your RAG pipeline to get the response
    #response = "This is a placeholder for the RAG response."
        answer1_with_knowledge = retrieval_chain.invoke({"input": selection})
        st.session_state.messages.append({"role": "assistant", "content": answer1_with_knowledge['answer']})
        st.rerun()
    
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if query1:=st.chat_input("Ask a question:"):
    with st.spinner("AI is thinking..."):
        st.session_state.messages.append({"role": "user", "content": query1 })
    # Here, call your RAG pipeline to get the response
    #response = "This is a placeholder for the RAG response."
        answer1_with_knowledge = retrieval_chain.invoke({"input": query1})
        st.session_state.messages.append({"role": "assistant", "content": answer1_with_knowledge['answer']})
        st.rerun()



time.sleep(2)