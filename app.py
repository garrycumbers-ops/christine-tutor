import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓", layout="wide")

# *** MODEL VERSION CONTROL ***
MODEL_NAME = "gemini-2.5-flash"

# 1. SECURE API KEY HANDLING
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
    3. **Image Analysis:** The user may upload a photo of written work or a textbook question.
       - Transcribe it (ignore minor spelling errors).
       - Analyze based on curriculum standards for Age {age}.
       - Provide "Glow" (Praise) and "Grow" (Improvement).
       - If it is a question they are stuck on, Scaffolding the answer.
    4. **Safety:** Do not answer active exam questions.
    """

def convert_history_for_gemini(history):
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        if isinstance(content, str):
            gemini_history.append({"role": role, "parts": [content]})
    return gemini_history

# --- MAIN APP UI ---
st.title("🎓 Christine: Your Personal Study Companion")

# --- SESSION STATE INITIALIZATION ---
if "camera_open" not in st.session_state:
    st.session_state.camera_open = False
if "captured_image" not in st.session_state:
    st.session_state.captured_image = None
if "last_processed_file_id" not in st.session_state:
    st.session_state.last_processed_file_id = None

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
        # --- SIDEBAR TOOLS ---
        st.sidebar.title(f"👤 {username}'s Space")
        current_subject = st.sidebar.text_input("Current Subject", value="General Study")
        st.sidebar.markdown("---")
        
        st.sidebar.header("📸 Submit Work")
        
        # 1. DOCUMENT SCANNER (BACK CAMERA on Mobile)
        # We relabel this to encourage using the system camera
        st.sidebar.info("📱 **On Mobile?** Use 'Scan Document' below -> Select 'Take Photo' to use your **Back Camera** & Flash.")
        file_input = st.sidebar.file_uploader("📂 Scan Document / Upload", type=['png', 'jpg', 'jpeg', 'webp'])
        
        st.sidebar.write("---")
        
        # 2. WEBCAM (Usually Front Camera)
        if st.session_state.captured_image is None:
            if not st.session_state.camera_open:
                if st.sidebar.button("📸 Use Webcam (Front)"):
                    st.session_state.camera_open = True
                    st.rerun()
            else:
                if st.sidebar.button("❌ Close Webcam"):
                    st.session_state.camera_open = False
                    st.rerun()
                    
                cam_input = st.sidebar.camera_input("Snap Photo")
                
                if cam_input:
                    st.session_state.captured_image = Image.open(cam_input)
                    st.session_state.camera_open = False # Switch off
                    st.rerun()
        else:
            st.sidebar.image(st.session_state.captured_image, caption="Webcam Photo", use_container_width=True)
            if st.sidebar.button("🗑️ Retake Webcam"):
                st.session_state.captured_image = None
                st.rerun()

        # --- CHAT HISTORY ---
        for msg in user_data["history"]:
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])

        # --- INPUT & PROCESSING ---
        user_text = st.chat_input("Type your question here...")

        # LOGIC: Check inputs
        active_image = None
        is_new_image = False
        
        # Priority: Webcam > File Upload
        if st.session_state.captured_image:
            active_image = st.session_state.captured_image
            file_id = f"cam-{str(active_image.size)}"
        elif file_input:
            active_image = file_input
            file_id = f"file-{file_input.name}-{file_input.size}"
        else:
            file_id = None

        if file_id and file_id != st.session_state.last_processed_file_id:
            is_new_image = True

        # TRIGGER
        if user_text or (is_new_image and active_image):
            
            display_text = user_text if user_text else ""
            current_turn_content = []
            
            if user_text: 
                current_turn_content.append(user_text)
            
            pil_image = None
            if active_image:
                try:
                    if isinstance(active_image, Image.Image):
                        pil_image = active_image
                    else:
                        pil_image = Image.open(active_image)
                        
                    current_turn_content.append(pil_image)
                    display_text += f"\n\n*[Attached Image]*"
                    
                    with st.chat_message("user"):
                        st.image(pil_image, caption="Work for Review")
                    
                    st.session_state.last_processed_file_id = file_id
                    
                except Exception as e:
                    st.error(f"Error processing image: {e}")

            if display_text and not active_image:
                 with st.chat_message("user"):
                    st.markdown(display_text)

            user_data["history"].append({"role": "user", "content": display_text})

            try:
                system_instruction = get_system_instruction(user_data["age"], current_subject, user_data["summary"])
                model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)
                chat_history = convert_history_for_gemini(user_data["history"][:-1])
                
                with st.chat_message("assistant"):
                    with st.spinner("Christine is analyzing..."):
                        if pil_image:
                            prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                            response = model.generate_content(prompt_parts)
                            
                            # Cleanup webcam image after sending
                            if st.session_state.captured_image:
                                st.session_state.captured_image = None
                        else:
                            chat = model.start_chat(history=chat_history)
                            response = chat.send_message(user_text)
                        
                        answer = response.text
                        st.markdown(answer)
                
                user_data["history"].append({"role": "model", "content": answer})
                save_data(db)

            except Exception as e:
                st.error(f"Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
