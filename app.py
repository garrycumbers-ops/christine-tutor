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
    # 3. Open the entire workbook, not just sheet1
    return gc.open("Christine Student Memory")

try:
    workbook = connect_to_sheets()
    sheet = workbook.sheet1  # Your main memory database stays completely safe!
    syllabus_sheet = workbook.worksheet("Syllabus") # The new roadmap tab
except Exception as e:
    st.error(f"Could not connect to Google Sheets. Check your exact spreadsheet name: {e}")

# --- NEW: SYLLABUS LOADER ---
def load_syllabus():
    try:
        records = syllabus_sheet.get_all_records()
        curriculum = {}
        for row in records:
            course = str(row.get("Course", "")).strip()
            topic = str(row.get("Topic", "")).strip()
            if course and topic:
                if course not in curriculum:
                    curriculum[course] = []
                curriculum[course].append(topic)
        return curriculum
    except Exception:
        return {"General Study": ["General Topic"]} # Safety fallback

def load_data():
    db = {}
    try:
        # THE FIX: get_all_values() ignores headers and just grabs the raw grid data!
        rows = sheet.get_all_values()
        
        if len(rows) <= 1:
            return db # Sheet is completely empty or only has headers
        
        # Skip the first row (the headers) and read the data
        for row in rows[1:]:
            # Safety net: ensure the row has exactly 5 columns now!
            while len(row) < 5:
                row.append("")
                
            # Grab strictly by Column Number (0=A, 1=B, 2=C, 3=D, 4=E)
            name_col = str(row[0]).strip().lower()
            summary_col = str(row[1]).strip()
            history_col = str(row[2]).strip()
            age_col = str(row[3]).strip()
            topic_col = str(row[4]).strip() # The new column!
            
            if name_col and name_col not in db:
                try:
                    hist = json.loads(history_col)
                except:
                    hist = []
                    
                if age_col == "" or age_col == "0":
                    student_age = None
                else:
                    student_age = age_col
                
                # Load the dossier AND the last topic into memory!
                db[name_col] = {
                    "summary": summary_col, 
                    "history": hist, 
                    "age": student_age, 
                    "last_topic": topic_col
                }
       
        return db
        
    except Exception as e:
        # Hard stop if Google is too slow
        st.error(f"⚠️ Database connection paused. Please refresh the page to try again. (System code: {e})")
        st.stop() 

def save_current_student(name, data):
    # This specifically updates just ONE student's row
    summary = data.get("summary", "")
    
    # --- THE ROLLING WINDOW ---
    # We only save the last 10 messages to prevent database overload!
    full_history = data.get("history", [])
    recent_history = full_history[-10:] if len(full_history) > 10 else full_history
    hist_str = json.dumps(recent_history)
    
    age = data.get("age", "") 
    last_topic = data.get("last_topic", "") # Grab the topic to save
    
    try:
        cell = sheet.find(name, in_column=1)
        sheet.update_cell(cell.row, 2, summary)
        sheet.update_cell(cell.row, 3, hist_str)
        sheet.update_cell(cell.row, 4, age)
        sheet.update_cell(cell.row, 5, last_topic) # Save to Column E
    except Exception:
        sheet.append_row([name, summary, hist_str, age, last_topic])

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
    Current Topic: {subject}
    Past Context (Bookmark & Gaps): {history_summary}

    CURRICULUM GOAL:
    You must PROACTIVELY guide the student through the "Current Topic". 
    CRITICAL RULE: Read the "Past Context" to see what they have already mastered. NEVER re-teach mastered concepts. Pick up exactly where the "Bookmark" leaves off and determine the NEXT logical concept.
    TEST-FIRST APPROACH: Do not just explain the next concept. You must test their knowledge on it FIRST before teaching.

    CORE GUIDELINES:
    1. **Strict Brevity & Slow Processing:** Responses must be extremely concise. Chunk complex ideas. Use short bullet points. NEVER output walls of text. Keep your total response as short as possible.
    2. **Tone:** Patient, encouraging, non-judgmental. Make learning feel like a fun, creative game. Never rush the student.
    3. **Voice Input Rule:** NEVER start your response with a microphone emoji, "Voice response," or a transcript of what the user said. Just answer directly.
    4. **Image Analysis:** The user may upload a photo of written work. Transcribe it, analyze based on Age {age} standards, provide short "Glow" and "Grow" feedback. Scaffold answers strictly ONE step at a time.
    5. **Safety & Exam Prep:** Do not answer *active/live* test questions to help a student cheat.
    6. **The Memory Rule:** NEVER use the Kevin Horsley memory techniques, peg systems, or bizarre imagery by default. Always teach standard academic concepts first.

    MODES OF OPERATION:
    
    A) TEST-FIRST TEACHING MODE (DEFAULT):
    1. Ask ONE short, diagnostic question about the next concept to see what they already know.
    2. STOP and wait for the student to answer. Do not give away the answer.
    3. If they answer correctly: Praise them, confirm they mastered it, and move immediately to testing the NEXT concept.
    4. If they answer incorrectly, partially correctly, or ask for help: Explain the concept simply in 1-to-2 sentences using 3 or 4 key facts.
    5. After explaining, proactively ask: "Would you like me to teach you a quick memory trick to lock this in?"

    B) MEMORY COACHING MODE (ONLY IF THE STUDENT SAYS YES TO A TRICK):
    1. Write vivid, bizarre image descriptions using the SEE Principle, strictly 1 or 2 punchy sentences per item.
    2. Apply the Number-Rhyme Peg System or Journey Method for ordered lists.
    3. Keep it fun and weird to help it stick in their brain!

    C) EXAM PREP (WHEN EXPLICITLY ASKED FOR A MULTIPLE-QUESTION QUIZ):
    1. If the student explicitly asks for multiple questions, provide a numbered list with that exact amount.
    2. STOP and wait for the student to answer.
    3. When they reply, grade their answers with a brief "Glow" (what they got right) and "Grow" (how to improve).
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
raw_username = st.text_input("Please enter your first name to begin:", key="username_input")
username = raw_username.strip().lower() if raw_username else ""

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
                
                # Grab what they were studying last, or use a default if it's blank
                saved_topic = db[username].get("last_topic", "a new topic")
                if saved_topic == "":
                    saved_topic = "a new topic"
                
                # THE CLEAN SLATE & GREETING
                st.session_state.user_data["history"] = [{
                    "role": "model", 
                    "content": f"Welcome back, {username.title()}! I've reviewed my notes, and it looks like we were working on **{saved_topic}**. Are you ready to pick up exactly where we left off, or do you want to switch topics?"
                }]
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
        
        # --- THE CURRICULUM ROADMAP ---
        st.sidebar.caption("🗺️ Your Learning Map")
        syllabus_data = load_syllabus()
        course_list = list(syllabus_data.keys())
        
        # 1. Figure out what they were studying last time
        saved_course_topic = user_data.get("last_topic", "")
        if ":" in saved_course_topic:
            default_course, default_topic = saved_course_topic.split(":", 1)
            default_course = default_course.strip()
            default_topic = default_topic.strip()
        else:
            default_course = course_list[0] if course_list else ""
            default_topic = ""

        # 2. Find the index numbers so the dropdowns snap to the right place
        course_index = course_list.index(default_course) if default_course in course_list else 0
        selected_course = st.sidebar.selectbox("Course:", course_list, index=course_index)

        topic_list = syllabus_data.get(selected_course, ["General Topic"])
        topic_index = topic_list.index(default_topic) if default_topic in topic_list else 0
        selected_topic = st.sidebar.selectbox("Current Topic:", topic_list, index=topic_index)
        
        # 3. Combine them and save it as the active subject
        current_subject = f"{selected_course}: {selected_topic}"

        # 4. If they changed the dropdown, update their memory file instantly!
        if current_subject != user_data.get("last_topic"):
            user_data["last_topic"] = current_subject
            save_current_student(username, user_data)

        st.sidebar.markdown("---")
        
        # Add the voice toggle right here!
        voice_on = st.sidebar.toggle("🔊 Read Christine's answers out loud")

         # --- NEW: STUDENT MEMORY ENGINE ---
        st.sidebar.header("🧠 Christine's Notes")
        st.sidebar.caption("Current Focus:")
        st.sidebar.info(user_data["summary"])

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
                
                # --- SILENT AUTO-DOSSIER ENGINE ---
                # THE FIX: Catch lengths of 8, 9, 16, 17, etc., so the math never skips!
                if len(user_data["history"]) in [8, 9, 16, 17, 24, 25]:
                    with st.spinner("Christine is taking notes on your progress..."):
                        try:
                            recent_chat = str(user_data["history"][-8:]) 
                            memory_prompt = f"""
                            You are an expert teacher maintaining a highly compressed, long-term dossier on a student.
                            
                            CURRENT DOSSIER: 
                            {user_data['summary']}
                            
                            RECENT CHAT: 
                            {recent_chat}
                            
                            TASK: Update the dossier to track their progress. 
                            
                            CRITICAL RULES FOR SPACE SAVING:
                            1. THE BOOKMARK: Write one short sentence at the top stating exactly what they just finished mastering so the tutor knows where to start next time (e.g., "BOOKMARK: Mastered Cell Walls, ready for Mitochondria").
                            2. RECORD GAPS: Log specific weaknesses or misunderstandings as bullet points. 
                            3. PRUNE RESOLVED ISSUES: If the recent chat shows they mastered a past weakness, DELETE it from the dossier.
                            4. BE RUTHLESS: Keep the entire dossier under 100 words.
                            """
                            
                            # Fallback Logic
                            try:
                                analyzer = genai.GenerativeModel(model_name=PRIMARY_MODEL)
                                memory_response = analyzer.generate_content(memory_prompt)
                            except Exception:
                                analyzer = genai.GenerativeModel(model_name=FALLBACK_MODEL)
                                memory_response = analyzer.generate_content(memory_prompt)
                            
                            user_data["summary"] = memory_response.text.strip()
                            
                        except Exception as e:
                            # THE FIX: Stop hiding errors! Show a small warning so we know if the API failed.
                            st.warning(f"Dossier update skipped. Error: {e}")

                # Save everything (chat and new summary) to Google Sheets
                save_current_student(username, user_data)


            except Exception as e:
                st.error(f"Connection Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
