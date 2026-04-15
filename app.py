import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image
from gtts import gTTS
import io
import re
import gspread

# --- GOOGLE SHEETS ENGINE ---
@st.cache_resource
def connect_to_sheets():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
    return gc.open("Christine Student Memory")

try:
    workbook = connect_to_sheets()
    sheet = workbook.sheet1
    syllabus_sheet = workbook.worksheet("Syllabus")
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
        return {"General Study": ["General Topic"]}

def load_data():
    db = {}
    try:
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return db
        
        for row in rows[1:]:
            while len(row) < 5:
                row.append("")
                
            name_col = str(row[0]).strip().lower()
            summary_col = str(row[1]).strip()
            history_col = str(row[2]).strip()
            age_col = str(row[3]).strip()
            topic_col = str(row[4]).strip()
            
            if name_col and name_col not in db:
                try:
                    hist = json.loads(history_col)
                except:
                    hist = []
                    
                student_age = None if (age_col == "" or age_col == "0") else age_col
                
                db[name_col] = {
                    "summary": summary_col, 
                    "history": hist, 
                    "age": student_age, 
                    "last_topic": topic_col
                }
        return db
    except Exception as e:
        st.error(f"⚠️ Database connection paused. Please refresh the page. (System code: {e})")
        st.stop() 

def save_current_student(name, data):
    summary = data.get("summary", "")
    full_history = data.get("history", [])
    recent_history = full_history[-10:] if len(full_history) > 10 else full_history
    hist_str = json.dumps(recent_history)
    age = data.get("age", "") 
    last_topic = data.get("last_topic", "")
    
    try:
        cell = sheet.find(name, in_column=1)
        sheet.update_cell(cell.row, 2, summary)
        sheet.update_cell(cell.row, 3, hist_str)
        sheet.update_cell(cell.row, 4, age)
        sheet.update_cell(cell.row, 5, last_topic)
    except Exception:
        sheet.append_row([name, summary, hist_str, age, last_topic])

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓", layout="wide")

PRIMARY_MODEL = "gemini-2.0-flash"
FALLBACK_MODEL = "gemini-2.5-flash"

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

def get_system_instruction(age, subject, history_summary):
    return f"""
    You are "Christine," an empathetic AI Educational Assistant and expert memory coach for students aged 11-18. 
    
    USER PROFILE:
    Age: {age}
    Current Topic: {subject}
    Past Context (Bookmark & Gaps): {history_summary}

    CURRICULUM GOAL:
    PROACTIVELY guide the student through the "Current Topic". 
    CRITICAL RULE: Read "Past Context" to see what they mastered. NEVER re-teach mastered concepts. Pick up exactly where the "Bookmark" leaves off and determine the NEXT logical concept.
    TEST-FIRST APPROACH: Do not just explain the next concept. You must test their knowledge on it FIRST before teaching.

    CORE GUIDELINES:
    1. **Strict Brevity & Slow Processing:** Responses must be extremely concise. Chunk complex ideas. Use short bullet points. NEVER output walls of text. Keep your total response as short as possible.
    2. **Tone:** Patient, encouraging, non-judgmental. Make learning feel like a fun, creative game. Never rush the student.
    3. **Voice Input Rule:** NEVER start your response with a microphone emoji, "Voice response," or a transcript of what the user said. Just answer directly.
    4. **Image Analysis:** The user may upload a photo of written work. Transcribe it, analyze based on Age {age} standards, provide short "Glow" and "Grow" feedback. Scaffold answers strictly ONE step at a time.
    5. **Safety & Exam Prep:** Do not answer *active/live* test questions to help a student cheat.
    6. **The Memory Rule:** NEVER use the Kevin Horsley memory techniques by default. Always teach standard academic concepts first.
    7. **STRICT GUARDRAILS:** Keep the student focused on the "Current Topic" ({subject}). HOWEVER, if they upload an image or file, this is an explicit SYSTEM OVERRIDE. You must temporarily pause the current topic and follow the exact instructions attached to their uploaded file.
    
    MODES OF OPERATION:
    A) TEST-FIRST TEACHING MODE (DEFAULT):
    1. Ask ONE short, diagnostic question about the next concept.
    2. STOP and wait for the student to answer. Do not give away the answer.
    3. If correct: Praise, confirm mastery, test the NEXT concept.
    4. If incorrect/help needed: Explain in 1-to-2 sentences using 3 or 4 key facts.
    5. Proactively ask: "Would you like me to teach you a quick memory trick to lock this in?"
    
    B) MEMORY COACHING MODE:
    1. Write vivid, bizarre image descriptions using the SEE Principle (1-2 sentences).
    2. Apply the Number-Rhyme Peg System or Journey Method.
    
    C) EXAM PREP:
    1. If explicitly asked for a quiz, provide a numbered list.
    2. STOP and wait for answers.
    3. Grade with "Glow" and "Grow".
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
if "camera_open" not in st.session_state: st.session_state.camera_open = False
if "captured_image" not in st.session_state: st.session_state.captured_image = None
if "last_processed_file_id" not in st.session_state: st.session_state.last_processed_file_id = None
if "unsummarized_messages" not in st.session_state: st.session_state.unsummarized_messages = 0
if "last_processed_audio_id" not in st.session_state: st.session_state.last_processed_audio_id = None
    
raw_username = st.text_input("Please enter your first name to begin:", key="username_input")
username = raw_username.strip().lower() if raw_username else ""

if username and api_key:
    genai.configure(api_key=api_key)
    
    if "user_data" not in st.session_state or st.session_state.get("current_user") != username:
        with st.spinner("Downloading profile..."):
            db = load_data()
            if username not in db:
                st.session_state.user_data = {"age": None, "history": [], "summary": "New student."}
            else:
                st.session_state.user_data = db[username]
                saved_topic = db[username].get("last_topic", "a new topic")
                if saved_topic == "": saved_topic = "a new topic"
                
                st.session_state.user_data["history"] = [{
                    "role": "model", 
                    "content": f"Welcome back, {username.title()}! I've reviewed my notes, and it looks like we were working on **{saved_topic}**. Are you ready to pick up exactly where we left off, or do you want to switch topics?"
                }]
            st.session_state.current_user = username

    user_data = st.session_state.user_data

    if not user_data.get("age"):
        st.info(f"Hi {username}! I'm Christine. Let's get set up.")
        col1, col2 = st.columns(2)
        with col1: age_input = st.number_input("How old are you?", min_value=11, max_value=18, step=1)
        with col2: subject_input = st.text_input("What subject are we doing today?")
            
        if st.button("Start Learning"):
            user_data["age"] = age_input
            user_data["history"].append({"role": "model", "content": f"Hello {username}! I'm ready to help you with {subject_input}. How can we start?"})
            save_current_student(username, user_data)
            st.rerun()
    else:
        # --- SIDEBAR TOOLS ---
        st.sidebar.title(f"👤 {username}'s Space")
        
        st.sidebar.caption("🗺️ Your Learning Map")
        syllabus_data = load_syllabus()
        course_list = list(syllabus_data.keys())
        
        saved_course_topic = user_data.get("last_topic", "")
        if ":" in saved_course_topic:
            default_course, default_topic = saved_course_topic.split(":", 1)
            default_course, default_topic = default_course.strip(), default_topic.strip()
        else:
            default_course = course_list[0] if course_list else ""
            default_topic = ""

        course_index = course_list.index(default_course) if default_course in course_list else 0
        selected_course = st.sidebar.selectbox("Course:", course_list, index=course_index)

        topic_list = syllabus_data.get(selected_course, ["General Topic"])
        topic_index = topic_list.index(default_topic) if default_topic in topic_list else 0
        selected_topic = st.sidebar.selectbox("Current Topic:", topic_list, index=topic_index)
        
        current_subject = f"{selected_course}: {selected_topic}"
      
        if current_subject != user_data.get("last_topic"):
            is_active_switch = user_data.get("last_topic") != ""
            user_data["last_topic"] = current_subject
            save_current_student(username, user_data)
            
            if is_active_switch:
                st.session_state.auto_submit_topic = current_subject
                st.rerun()

        st.sidebar.markdown("---")
        voice_on = st.sidebar.toggle("🔊 Read Christine's answers out loud")

        st.sidebar.header("🧠 Christine's Notes")
        st.sidebar.info(user_data["summary"])
        st.sidebar.markdown("---")
        
        st.sidebar.header("📸 Submit Work")
        
        # --- NEW: Image Action Selector ---
        image_action = st.sidebar.radio(
            "Step 1: What should Christine do?",
            ["Review my work for mistakes", "Quiz me on this content"]
        )
        st.sidebar.caption("Step 2: Upload or snap your photo:")
        
        file_input = st.sidebar.file_uploader("Upload File", type=['png', 'jpg', 'jpeg', 'webp'])
        st.sidebar.write("OR")
        
        if st.session_state.captured_image:
            st.sidebar.image(st.session_state.captured_image, caption="Ready to send", use_container_width=True)
            if st.sidebar.button("🗑️ Discard & Retake"):
                st.session_state.captured_image = None
                st.session_state.camera_open = True
                st.rerun()
        else:
            if not st.session_state.camera_open:
                if st.sidebar.button("📸 Open Camera"):
                    st.session_state.camera_open = True
                    st.rerun()
            else:
                if st.sidebar.button("❌ Close Camera"):
                    st.session_state.camera_open = False
                    st.rerun()
                cam_input = st.sidebar.camera_input("Take Photo")
                if cam_input:
                    st.session_state.captured_image = Image.open(cam_input)
                    st.session_state.camera_open = False
                    st.rerun()

        # --- SILENT AUTO-DOSSIER ENGINE ---
        if st.session_state.unsummarized_messages >= 14:
            with st.spinner("Christine is organizing her notes..."):
                try:
                    grab_count = st.session_state.unsummarized_messages
                    recent_chat = str(user_data["history"][-grab_count:]) 
                    
                    memory_prompt = f"""
                    You are an expert teacher maintaining a highly compressed, long-term dossier on a student.
                    CURRENT DOSSIER: {user_data['summary']}
                    RECENT CHAT: {recent_chat}
                    TASK: Update the dossier to track their progress.
                    CRITICAL RULES:
                    1. THE BOOKMARK: Write one short sentence stating exactly what they just mastered.
                    2. RECORD GAPS: Log specific weaknesses. IGNORE off-topic chatter.
                    3. PRUNE: DELETE mastered weaknesses. Keep under 100 words.
                    """
                    try:
                        analyzer = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")
                        memory_response = analyzer.generate_content(memory_prompt)
                    except Exception:
                        analyzer = genai.GenerativeModel(model_name=FALLBACK_MODEL)
                        memory_response = analyzer.generate_content(memory_prompt)
                    
                    user_data["summary"] = memory_response.text.strip()
                    st.session_state.unsummarized_messages = 0
                    save_current_student(username, user_data)
                except Exception as e:
                    st.warning(f"Dossier update skipped. Error: {e}")

        # --- CHAT HISTORY ---
        for msg in user_data["history"]:
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])

        # --- INPUT & PROCESSING ---
        st.markdown("""
            <style>
            [data-testid="stAudioInput"] { position: fixed; bottom: 85px; z-index: 999; }
            .block-container { padding-bottom: 150px !important; }
            </style>
            """, unsafe_allow_html=True)

        user_audio = st.audio_input("🎤 Talk to Christine")
        user_text = st.chat_input("...or type your question here")

        active_image = None
        is_new_image = False
        
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

        is_new_audio = False
        audio_id = None
        if user_audio:
            audio_id = f"audio-{user_audio.size}"
            if audio_id != st.session_state.last_processed_audio_id:
                is_new_audio = True

        auto_topic = st.session_state.pop("auto_submit_topic", None)
        
        has_text = bool(user_text)
        has_image = bool(is_new_image and active_image)
        has_audio = bool(is_new_audio and user_audio)
        
        if has_text or has_image or has_audio or auto_topic:
            
            display_text = user_text if user_text else ""
            current_turn_content = []
            
            if auto_topic:
                display_text = f"I am switching topics to **{auto_topic}**. Please check my dossier and test me on the next concept I need to learn."
                current_turn_content.append(display_text)
                
            if has_text: 
                current_turn_content.append(user_text)

            if has_audio:
                audio_part = {"mime_type": "audio/wav", "data": user_audio.getvalue()}
                current_turn_content.append(audio_part)
                display_text += "\n\n[🎤 Voice Message]"
                st.session_state.last_processed_audio_id = audio_id
            
            pil_image = None
            if has_image:
                try:
                    pil_image = active_image if isinstance(active_image, Image.Image) else Image.open(active_image)
                    current_turn_content.append(pil_image)
                    
                    # --- NEW: Inject the student's chosen action ---
                    if image_action == "Review my work for mistakes":
                        action_prompt = "SYSTEM OVERRIDE: Temporarily pause the current topic. Please carefully review my attached work. Tell me what I did right and help me correct any mistakes one step at a time."
                    else:
                        action_prompt = "SYSTEM OVERRIDE: Temporarily pause the current topic. Please thoroughly analyze this attached content and ask me a diagnostic quiz question strictly based on the material in this image."

                    display_text += f"\n\n[📸 Attached Image: {action_prompt}]"
                    st.session_state.last_processed_file_id = file_id
                except Exception as e:
                    st.error(f"Error processing image: {e}")
                    
            with st.chat_message("user"):
                if auto_topic: st.markdown(f"*(Switched topic to {auto_topic})*")
                if has_text: st.markdown(user_text)
                if has_image and pil_image: st.image(pil_image, caption="Work for Review")
                if has_audio: st.audio(user_audio) 
            
            user_data["history"].append({"role": "user", "content": display_text})

            # --- AI GENERATION ---
            try:
                system_instruction = get_system_instruction(user_data["age"], current_subject, user_data["summary"])
                
                # Prevent empty message bug from ghost history
                chat_history = convert_history_for_gemini([msg for msg in user_data["history"][:-1] if msg.get("content")])
                
                # Ensure first message in history is from a user for Gemini API
                if chat_history and chat_history[0]["role"] != "user":
                    chat_history.insert(0, {"role": "user", "parts": ["Hello"]})

                with st.chat_message("assistant"):
                    with st.spinner("Christine is analyzing..."):
                        try:
                            model = genai.GenerativeModel(
                                model_name=PRIMARY_MODEL, 
                                system_instruction=system_instruction
                            )
                            if has_image or has_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(display_text)
                        except Exception:
                            model = genai.GenerativeModel(
                                model_name=FALLBACK_MODEL, 
                                system_instruction=system_instruction
                            )
                            if has_image or has_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(display_text)
                    
                        answer = response.text.replace("🎤 Voice Response", "").replace("🎤 Voice response", "").replace("🎤 Voice Message", "").replace("🎤 [Voice Message]", "").replace("*[🎤 Voice Message]*", "").strip()
                        
                        if not answer:
                            answer = "I'm sorry, I had trouble processing that. Could you try asking again?"
                            
                        st.markdown(answer)
                        
                        if voice_on:
                            try:
                                clean_speech = answer.replace('**', '').replace('#', '').replace('`', '').replace('_', '')
                                clean_speech = re.sub(r'^\s*[\*\-]\s+', ' ', clean_speech, flags=re.MULTILINE)
                                clean_speech = re.sub(r'\s+', ' ', clean_speech).strip()
                                
                                sound_file = io.BytesIO()
                                tts = gTTS(text=clean_speech, lang='en', tld='co.uk')
                                tts.write_to_fp(sound_file)
                                sound_file.seek(0)
                                
                                st.audio(sound_file, format='audio/mpeg', autoplay=True)
                            except Exception as e:
                                st.error(f"Audio generation skipped: {e}")
                
                        if st.session_state.captured_image:
                            st.session_state.captured_image = None
                
                user_data["history"].append({"role": "model", "content": answer})
                save_current_student(username, user_data)
                st.session_state.unsummarized_messages += 2

            except Exception as e:
                 st.error(f"Connection Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
