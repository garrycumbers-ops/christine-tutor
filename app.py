import streamlit as st
import google.generativeai as genai
import os

st.title("🛠 Model Finder Tool")

# 1. Get API Key
api_key = None
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.text_input("Enter Gemini API Key", type="password")

if api_key:
    genai.configure(api_key=api_key)
    
    st.write("### 🔍 Scanning for available models...")
    
    try:
        available_models = []
        # List all models
        for m in genai.list_models():
            # We only care about models that can "generateContent" (chat)
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        if available_models:
            st.success(f"Found {len(available_models)} working models!")
            st.write("### ✅ Copy one of these exact names into your main app.py:")
            st.code(available_models)
        else:
            st.error("No models found. Your API Key might be invalid or have no service enabled.")
            
    except Exception as e:
        st.error(f"Error scanning models: {e}")
