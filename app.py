import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image
from google.api_core.exceptions import GoogleAPIError

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓")

# 1. SECURE API KEY HANDLING
# This checks if the key is stored in the cloud secrets (Deployment) 
# or asks for it in the sidebar (Testing).
api_key = None
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

# File to store history
DB_FILE = "student_history.json"

# --- HELPER FUNCTIONS ---
def load_data():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_system_instruction(age, subject, history_summary):
    return f"""
    You are "Christine," an empathetic AI Educational Assistant for students aged 11-18.
    
    USER PROFILE:
    Age: {age}
    Subject: {subject}
    Past Context: {history_summary}

    CORE GUIDELINES:
    1. **Slow Processing Support:** Chunk complex questions. Use bullet points. NO walls of text.
    2. **Tone:** Patient, encouraging, non-judgmental. Never rush the student.
    3. **Image Analysis:** If an image is provided:
       - Transcribe it (ignore minor spelling errors).
       - Analyze based on curriculum standards for Age {age}.
       - Provide "Glow" (What went well) and "Grow" (One specific improvement).
       - Ask a follow-up check question.
    4. **Safety:** Do not answer active exam questions. If frustration is detected, suggest a brain break.
    5. **Scaffolding:** Provide hints, not answers.
    """

def convert_history_for_gemini(history):
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        # Ensure content is a string for history reconstruction
        if isinstance(content, str):
            gemini_history.append({"role": role, "parts": [content]})
    return gemini_history

# --- MAIN APP UI ---
st.title("🎓 Christine: Your Personal Study Companion")

# USER IDENTIFICATION
username = st.text_input("Please enter your first name to begin:", key="username_input")

if username and api_key:
    genai.configure(api_key=api_key)
    db = load_data()
    
    if username not in db:
        db[username] = {"age": None, "history": [], "summary": "New student."}
    
    user_data = db[username]

    # SESSION INITIALIZATION
    if not user_data["age"]:
        st.info(f"Hi {username}! I'm Christine. Let's get set up.")
        col1, col2 = st.columns(2)
        with col1:
            age_input = st.number_input("How old are you?", min_value=11, max_value=18, step=1)
        with col2:
            subject_input = st.text_input("What subject are we doing today?")
            
        if st.button("Start Learning"):
            user_data["age"] = age_input
            user_data["history"].append({
                "role": "model",
                "content": f"Hello {username}! I'm ready to help you with {subject_input}. How can we start?"
            })
            save_data(db)
            st.rerun()
    else:
        # CHAT INTERFACE
        current_subject = st.sidebar.text_input("Current Subject", value="General Study")
        
        for msg in user_data["history"]:
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])

        user_text = st.chat_input("Type here...")
        uploaded_file = st.sidebar.file_uploader("Upload work (photo)", type=['png', 'jpg', 'jpeg', 'webp'])

        if user_text or uploaded_file:
            display_text = user_text if user_text else ""
            current_turn_content = []
            
            if user_text: current_turn_content.append(user_text)
            
            pil_image = None
            if uploaded_file:
                try:
                    pil_image = Image.open(uploaded_file)
                    current_turn_content.append(pil_image)
                    display_text += "\n\n*[Image Uploaded]*"
                    with st.chat_message("user"):
                        st.image(uploaded_file, caption="My Work")
                except:
                    st.error("Error loading image.")

            if display_text and not uploaded_file:
                 with st.chat_message("user"):
                    st.markdown(display_text)

            user_data["history"].append({"role": "user", "content": display_text})

            try:
                system_instruction = get_system_instruction(user_data["age"], current_subject, user_data["summary"])
                model = genai.GenerativeModel(model_name="gemini-2.5-flash", system_instruction=system_instruction)
                chat_history = convert_history_for_gemini(user_data["history"][:-1])
                
                with st.chat_message("assistant"):
                    with st.spinner("Christine is thinking..."):
                        if pil_image:
                            prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                            response = model.generate_content(prompt_parts)
                        else:
                            chat = model.start_chat(history=chat_history)
                            response = chat.send_message(user_text)
                        
                        answer = response.text
                        st.markdown(answer)
                
                user_data["history"].append({"role": "model", "content": answer})
                if len(user_data["history"]) % 6 == 0:
                     user_data["summary"] += f" | Interaction on {current_subject}."
                save_data(db)

            except Exception as e:
                st.error(f"Error: {e}")

elif not api_key:
     st.warning("System Setup Required: API Key missing in Secrets.")
