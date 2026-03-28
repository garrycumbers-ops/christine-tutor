import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image
from gtts import gTTS
import io
import re
import json
import gspread

# --- GOOGLE SHEETS ENGINE ---
@st.cache_resource
def connect_to_sheets():
    # 1. Open the vault and grab the keys
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    # 2. Hand the keys to the Google robot
    gc = gspread.service_account_from_dict(creds_dict)
    # 3. Open your specific spreadsheet (Make sure this name matches exactly!)
    return gc.open("Christine Student Memory").sheet1

try:
    sheet = connect_to_sheets()
except Exception as e:
    st.error(f"Could not connect to Google Sheets. Check your exact spreadsheet name: {e}")

def load_data():
    db = {}
    try:
        # Download the whole spreadsheet into Christine's brain
        records = sheet.get_all_records()
        for row in records:
            try:
                hist = json.loads(row["History"])
            except:
                hist = []
                
            # Grab the age from the new column!
            student_age = row.get("Age", None)
            if student_age == "":  # Handle empty cells
                student_age = None
                
            db[str(row["Name"])] = {"summary": str(row["Summary"]), "history": hist, "age": student_age}
    except Exception as e:
        pass # Fails silently if the sheet is completely blank
    return db

def save_current_student(name, data):
    # This specifically updates just ONE student's row so it is lightning fast
    summary = data.get("summary", "")
    hist_str = json.dumps(data.get("history", []))
    age = data.get("age", "") # Grab the age from memory
    
    try:
        # Look for the student's name in Column 1 (A)
        cell = sheet.find(name, in_column=1)
        # If found, update Summary (Col 2), History (Col 3), and Age (Col 4)
        sheet.update_cell(cell.row, 2, summary)
        sheet.update_cell(cell.row, 3, hist_str)
        sheet.update_cell(cell.row, 4, age)
        
    except Exception:
        # If they are a brand new student, add them to the bottom of the sheet!
        sheet.append_row([name, summary, hist_str, age])

# ----------------------------------

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓", layout="wide")

# *** MODEL VERSION CONTROL ***
# Tries the newest model first, falls back if your key doesn't have access yet.
PRIMARY_MODEL = "gemini-2.0-flash"
FALLBACK_MODEL = "gemini-2.5-flash"

# 1. SECURE API KEY HANDLING
api_key = None
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

def get_system_instruction(age, subject, history_summary):
    return f"""
    You are "Christine," an empathetic AI Educational Assistant and expert memory coach for students aged 11-18. You specialize in interactive learning, exam preparation, and Kevin Horsley's 'Unlimited Memory' techniques.
    
    USER PROFILE:
    Age: {age}
    Subject: {subject}
    Past Context: {history_summary}

    CORE GUIDELINES:
    1. **Strict Brevity & Slow Processing:** Responses must be extremely concise. Chunk complex ideas. Use short bullet points. NEVER output walls of text. Keep your total response as short as possible.
    2. **Tone:** Patient, encouraging, non-judgmental. Make learning feel like a fun, creative game. Never rush the student.
    3. **Voice Input Rule:** NEVER start your response with a microphone emoji, "Voice response," or a transcript of what the user said. Just answer directly.
    4. **Image Analysis:** The user may upload a photo of written work. Transcribe it, analyze based on Age {age} standards, provide short "Glow" and "Grow" feedback. Scaffold answers strictly ONE step at a time.
    5. **Safety & Exam Prep:** Do not answer *active/live* test questions to help a student cheat. HOWEVER, enthusiastically welcome requests for practice tests, quizzing, and exam prep!

    MODES OF OPERATION:
    
    A) WHEN ASKED TO TEACH OR MEMORIZE (KEVIN HORSLEY METHOD):
    1. Give a 1-to-2 sentence ultra-simple explanation of the core concept.
    2. Pick ONLY the top 3 or 4 facts to start. 
    3. Write vivid, bizarre image descriptions using the SEE Principle, strictly 1 or 2 punchy sentences per item.
    4. Apply the Number-Rhyme Peg System or Journey Method for ordered lists.

    B) WHEN ASKED TO TEST OR PREPARE FOR EXAMS (QUIZ MODE):
    1. Ask ONE practice question at a time related to their subject.
    2. STOP and wait for the student to answer. Do not give away the answer.
    3. When they reply, provide a brief "Glow" (what they got right) and "Grow" (how to improve).
    4. If they get it wrong or struggle, proactively offer a quick Kevin Horsley memory trick to help them lock it in for the real exam!
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
st.title("🎓 Christine: AI Tutor")

# --- SESSION STATE SETUP ---
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
    
    # --- FAST MEMORY ---
    # Only download from Google once per login to avoid lag!
    if "user_data" not in st.session_state or st.session_state.get("current_user") != username:
        with st.spinner("Downloading profile..."):
            db = load_data()
            if username not in db:
                st.session_state.user_data = {"age": None, "history": [], "summary": "New student."}
            else:
                st.session_state.user_data = db[username]
            st.session_state.current_user = username
            
    # Read from the fast memory, not Google Sheets
    user_data = st.session_state.user_data

    # SESSION INITIALIZATION
    if not user_data.get("age"):
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
            save_current_student(username, user_data)
            st.rerun()
    else:
        # --- SIDEBAR TOOLS ---
        st.sidebar.title(f"👤 {username}'s Space")
        current_subject = st.sidebar.text_input("Current Subject", value="General Study")
        st.sidebar.markdown("---")
        
        # Add the voice toggle right here!
        voice_on = st.sidebar.toggle("🔊 Read Christine's answers out loud")

         # --- NEW: STUDENT MEMORY ENGINE ---
        st.sidebar.header("🧠 Christine's Notes")
        st.sidebar.caption("Current Focus:")
        st.sidebar.info(user_data["summary"])
        
        if st.sidebar.button("📝 Analyze Session & Update Profile"):
            with st.spinner("Christine is analyzing your progress..."):
                try:
                    recent_chat = str(user_data["history"][-10:]) 
                    memory_prompt = f"""
                    You are an expert teacher analyzing a student's recent chat history.
                    Current Profile: {user_data['summary']}
                    Recent Chat: {recent_chat}
                    
                    TASK: Update the student's profile in exactly 2 or 3 sentences. 
                    Focus strictly on their weaknesses, the specific mistakes they just made, and what topics or concepts they need to review next time. Do not use formatting.
                    """
                    analyzer = genai.GenerativeModel(model_name=PRIMARY_MODEL)
                    memory_response = analyzer.generate_content(memory_prompt)
                    
                    user_data["summary"] = memory_response.text.strip()
                    
                    # ---> SAVE TO GOOGLE SHEETS <---
                    save_current_student(username, user_data)
                    st.rerun()
                except Exception as e:
                    st.sidebar.error("Could not update memory right now.")
        st.sidebar.markdown("---")
        
        st.sidebar.header("📸 Submit Work")

        # 1. FILE UPLOAD (Always Visible)
        file_input = st.sidebar.file_uploader("Upload File", type=['png', 'jpg', 'jpeg', 'webp'])
        
        st.sidebar.write("OR")
        
        # 2. CAMERA LOGIC (Snap & Close)
        # If we have a captured image in memory, show it.
        if st.session_state.captured_image:
            st.sidebar.image(st.session_state.captured_image, caption="Ready to send", use_container_width=True)
            if st.sidebar.button("🗑️ Discard & Retake"):
                st.session_state.captured_image = None
                st.session_state.camera_open = True # Re-open immediately for convenience
                st.rerun()
        
        # If no image, handle the Camera Toggle
        else:
            if not st.session_state.camera_open:
                # Camera is OFF. Show 'Open' button.
                if st.sidebar.button("📸 Open Camera"):
                    st.session_state.camera_open = True
                    st.rerun()
            else:
                # Camera is ON. Show 'Close' button and Widget.
                if st.sidebar.button("❌ Close Camera"):
                    st.session_state.camera_open = False
                    st.rerun()
                
                # The Widget
                cam_input = st.sidebar.camera_input("Take Photo")
                
                # If photo is taken, save and CLOSE immediately
                if cam_input:
                    st.session_state.captured_image = Image.open(cam_input)
                    st.session_state.camera_open = False # Turn off hardware
                    st.rerun()

        # --- CHAT HISTORY ---
        for msg in user_data["history"]:
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])

        # --- INPUT & PROCESSING ---
        
        # Inject CSS to float the microphone at the bottom
        st.markdown("""
            <style>
            /* Pin the microphone just above the chat text box */
            [data-testid="stAudioInput"] {
                position: fixed;
                bottom: 85px; 
                z-index: 999;
            }
            /* Add padding to the bottom of the page so chat messages don't hide behind the mic */
            .block-container {
                padding-bottom: 150px !important;
            }
            </style>
            """, unsafe_allow_html=True)

        user_audio = st.audio_input("🎤 Talk to Christine")
        user_text = st.chat_input("...or type your question here")


        # Determine if we have an image to process
        active_image = None
        is_new_image = False
        
        # Priority: Camera State > File Upload
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
        if user_text or (is_new_image and active_image) or user_audio:
            
            display_text = user_text if user_text else ""
            current_turn_content = []
            
            if user_text: 
                current_turn_content.append(user_text)

            # --- NEW: Process Audio ---
            if user_audio:
                audio_part = {
                    "mime_type": "audio/wav",
                    "data": user_audio.getvalue()
                }
                current_turn_content.append(audio_part)
                display_text += "\n\n[🎤 Voice Message]"
            
            # --- Process Image ---
            pil_image = None
            if active_image:
                try:
                    if isinstance(active_image, Image.Image):
                        pil_image = active_image
                    else:
                        pil_image = Image.open(active_image)
                        
                    current_turn_content.append(pil_image)
                    display_text += f"\n\n[📸 Attached Image]"
                    st.session_state.last_processed_file_id = file_id
                except Exception as e:
                    st.error(f"Error processing image: {e}")

            # --- Clean UI Display for the Student ---
            with st.chat_message("user"):
                if user_text:
                    st.markdown(user_text)
                if active_image and pil_image:
                    st.image(pil_image, caption="Work for Review")
                if user_audio:
                    st.audio(user_audio) # Shows an audio player so they know it sent!

            user_data["history"].append({"role": "user", "content": display_text})

            # --- AI GENERATION ---
            try:
                system_instruction = get_system_instruction(user_data["age"], current_subject, user_data["summary"])
                chat_history = convert_history_for_gemini(user_data["history"][:-1])
                
                with st.chat_message("assistant"):
                    with st.spinner("Christine is analyzing..."):
                        
                        # Fallback Model Logic
                        try:
                            # Try Primary Model
                            model = genai.GenerativeModel(model_name=PRIMARY_MODEL, system_instruction=system_instruction)
                            if pil_image or user_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(user_text)
                        except Exception:
                            # Try Fallback Model
                            model = genai.GenerativeModel(model_name=FALLBACK_MODEL, system_instruction=system_instruction)
                            if pil_image or user_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(user_text)
                        
                        answer = response.text
                        
                        # --- CLEANUP: Stop the AI from mimicking the mic label ---
                        answer = answer.replace("🎤 Voice Response", "")
                        answer = answer.replace("🎤 Voice response", "")
                        answer = answer.replace("🎤 Voice Message", "")
                        answer = answer.replace("🎤 [Voice Message]", "")
                        answer = answer.replace("*[🎤 Voice Message]*", "")
                        
                        # Strip any leftover blank lines or spaces at the top
                        answer = answer.strip()
                        
                        st.markdown(answer)
                        
                        # --- NEW AUDIO BLOCK START ---
                        if voice_on:
                            try:
                                clean_speech = answer.replace('**', '').replace('#', '').replace('`', '').replace('_', '')
                                clean_speech = re.sub(r'^\s*[\*\-]\s+', ' ', clean_speech, flags=re.MULTILINE)
                                clean_speech = re.sub(r'\s+', ' ', clean_speech).strip()
                                
                                sound_file = io.BytesIO()
                                tts = gTTS(text=clean_speech, lang='en', tld='co.uk')
                                tts.write_to_fp(sound_file)
                                
                                # THE FIX: Rewind the virtual tape back to 0 seconds!
                                sound_file.seek(0)
                                
                                # THE APPLE FIX: Changed format from audio/mp3 to audio/mpeg
                                st.audio(sound_file, format='audio/mpeg', autoplay=True)
                            except Exception as e:
                                st.error(f"Audio generation skipped: {e}")
                        # --- NEW AUDIO BLOCK END ---
                        
                        # Clean up camera image after successful send
                        if st.session_state.captured_image:
                            st.session_state.captured_image = None
                
                user_data["history"].append({"role": "model", "content": answer})
                save_current_student(username, user_data)

            except Exception as e:
                st.error(f"Connection Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
