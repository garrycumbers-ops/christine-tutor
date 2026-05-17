import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image
from gtts import gTTS
import io
import re
import gspread
import threading
import time

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
            while len(row) < 6:
                row.append("")
                
            name_col = str(row[0]).strip().lower()
            summary_col = str(row[1]).strip()
            history_col = str(row[2]).strip()
            age_col = str(row[3]).strip()
            topic_col = str(row[4]).strip()
            vault_col = str(row[5]).strip() 
            
            if name_col:
                try:
                    hist = json.loads(history_col)
                except:
                    hist = []
                    
                student_age = None if (age_col == "" or age_col == "0") else age_col
                
                db[name_col] = {
                    "summary": summary_col, 
                    "history": hist, 
                    "age": student_age, 
                    "last_topic": topic_col,
                    "file_vault": vault_col 
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
    file_vault = data.get("file_vault", "") 
    
    try:
        cell = sheet.find(name, in_column=1)
        sheet.update_cell(cell.row, 2, summary)
        sheet.update_cell(cell.row, 3, hist_str)
        sheet.update_cell(cell.row, 4, age)
        sheet.update_cell(cell.row, 5, last_topic)
        sheet.update_cell(cell.row, 6, file_vault)
    except Exception:
        sheet.append_row([name, summary, hist_str, age, last_topic, file_vault])

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓", layout="wide")

PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-flash-lite"

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

# --- PURE gTTS AUDIO GENERATOR ---
def generate_audio_bytes(text):
    '''Uses synchronous gTTS. 100% crash proof inside Streamlit.'''
    try:
        safe_text = text[:1500] 
        tts = gTTS(text=safe_text, lang='en', tld='co.uk')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp.getvalue()
    except Exception as e:
        st.error(f"Audio Generation Error: {e}")
        return None

def clean_text_for_speech(text):
    clean_speech = re.sub(r'!\[.*?\]\((.*?)\)', '', text)
    clean_speech = re.sub(r'\[.*?\]\((.*?)\)', '', clean_speech)
    clean_speech = re.sub(r'http[s]?://\S+', '', clean_speech) 
    clean_speech = clean_speech.replace('**', '').replace('#', '').replace('`', '').replace('_', '')
    clean_speech = re.sub(r'^\s*[\*\-]\s+', ' ', clean_speech, flags=re.MULTILINE)
    return re.sub(r'\s+', ' ', clean_speech).strip()

# --- BACKGROUND DOSSIER SAVER (INACTIVITY TIMER) ---
def background_dossier_save(username, chat_history_str, selected_topic):
    '''Runs silently in a background thread when the student stops typing for 5 minutes.'''
    try:
        db = load_data()
        if username not in db: return
        user_data = db[username]
        
        summary_model = genai.GenerativeModel(model_name=FALLBACK_MODEL)
        
        memory_prompt = f'''
        You are an expert teacher maintaining a highly compressed, long-term dossier on a student.
        CURRENT DOSSIER: {user_data.get('summary', '')}
        RECENT CHAT: {chat_history_str}
        
        TASK: Update the CURRENT DOSSIER with new insights from the RECENT CHAT.
        
        CRITICAL RULES:
        1. PRESERVE ALL OTHER TOPICS: You MUST keep all existing tags and notes for OTHER subjects exactly as they appear in the CURRENT DOSSIER. DO NOT delete them!
        2. MASTERED TAGS: Start new or updated lines with exact format: [{selected_topic}] MASTERED:
        3. GAP TAGS: Start new or updated lines with exact format: [{selected_topic}] GAP:
        4. PRUNE: If they master a previous GAP in {selected_topic}, delete that specific GAP tag. 
        5. DOCUMENT PROGRESS: If they are working on a saved document, explicitly state which specific questions or paragraphs they have ALREADY finished.
        '''
        response = summary_model.generate_content(memory_prompt)
        user_data["summary"] = response.text.strip()
        
        save_current_student(username, user_data)
        print(f"✅ Inactivity Timer triggered! Dossier saved for {username}.")
    except Exception as e:
        print(f"Background save failed: {e}")

# --- AI BRAIN RULES ---
def get_system_instruction(age, subject, history_summary, file_vault="", has_hidden_vault=False):
    # 1. Load the Universal AQA Master Document
    try:
        with open("aqa_master_rubric.txt", "r", encoding="utf-8") as f:
            aqa_knowledge = f.read()
    except FileNotFoundError:
        aqa_knowledge = "[System: AQA Rubric file not found. Rely on general GCSE knowledge.]"

    # 2. Handle the Student's Personal Vault
    if file_vault:
        vault_text = f"\n\nSAVED STUDENT DOCUMENT:\nThe student has saved this document to memory:\n{file_vault}"
    elif has_hidden_vault:
        vault_text = "\n\n[SYSTEM NOTE: The student has a large document saved, but it is TURNED OFF.]"
    else:
        vault_text = ""

    # 3. Assemble the Ultimate Socratic Prompt
    return f'''
    You are "Christine," an elite Socratic AQA GCSE English Tutor specializing in pushing students from Grade 5s to Grade 9s.

    USER PROFILE:
    Age: {age} (GCSE Student)
    Current Topic/Text: {subject}
    Past Context (Mastery & Gaps): {history_summary}
    {vault_text}

    ====================
    OFFICIAL AQA KNOWLEDGE BASE & EXAMINER REPORTS:
    You must base all grading, feedback, and Socratic questions strictly on this data:
    {aqa_knowledge}
    ====================

    CURRICULUM GOAL:
    Act as a rigorous "digital supervisor." Your goal is to force the student to develop highly sophisticated, perceptive arguments using the AQA Knowledge Base above.

    CRITICAL SOCRATIC RULES:
    1. NEVER do the work for them: NEVER provide summaries, quotes, or pre-written PEEL paragraphs.
    2. The "So What?" Loop: If a student identifies a technique, DO NOT just say "Well done." You MUST ask: "Correct. But so what? How does that specific technique manipulate the reader's view of the theme in this exact moment?"
    3. Contextual Intent (AO3): Force them to connect context directly to the writer's overarching message or intent.
    4. AQA Marker Persona: When reviewing answers, explicitly map their successes or gaps to the AQA Assessment Objectives (AO1, AO2, AO3) listed in your Knowledge Base. Quote the examiner reports to them if they make common mistakes.
    5. Anti-PEEL: Discourage robotic structures and force perceptive, conceptual tracking.
    6. Voice/Tone: Academic, rigorously challenging, yet encouraging. Never use emojis. NEVER start your response with a microphone emoji.
    '''
    
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
if "use_vault" not in st.session_state: st.session_state.use_vault = False

# Safely initialize the auto_play_text tracker
if "auto_play_text" not in st.session_state:
    st.session_state.auto_play_text = None
    
raw_username = st.text_input("Please enter your first name to begin:", key="username_input")
username = raw_username.strip().lower() if raw_username else ""

if username and api_key:
    genai.configure(api_key=api_key)
    
    if "user_data" not in st.session_state or st.session_state.get("current_user") != username:
        with st.spinner("Downloading profile..."):
            st.session_state.last_processed_file_id = None
            st.session_state.last_processed_audio_id = None
            st.session_state.captured_image = None
            
            db = load_data()
            if username not in db:
                st.session_state.user_data = {"age": None, "history": [], "summary": "New student.", "file_vault": ""}
            else:
                st.session_state.user_data = db[username]
                saved_topic = db[username].get("last_topic", "a new topic")
                if saved_topic == "": saved_topic = "a new topic"
                
                if len(st.session_state.user_data.get("history", [])) == 0:
                    if db[username].get("file_vault", "").strip():
                        welcome_msg = f"Welcome back, {username.title()}! I see you have a document saved in your Vault. If you want to use it today, just turn on **'📖 Use Vault Document in Chat'** in the sidebar. Otherwise, how can we start?"
                    else:
                        welcome_msg = f"Welcome back, {username.title()}! How can we start today?"
                    
                    st.session_state.user_data["history"] = [{
                        "role": "model", 
                        "content": welcome_msg
                    }]
            st.session_state.current_user = username

    user_data = st.session_state.user_data
    
    # Initialize auto_topic for the direct execution flow
    auto_topic = None

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
      
        # --- NO-RERUN TOPIC SWITCH LOGIC FIX ---
        if current_subject != user_data.get("last_topic"):
            is_active_switch = user_data.get("last_topic") != ""
            user_data["last_topic"] = current_subject
            save_current_student(username, user_data)
            
            if is_active_switch:
                if st.session_state.unsummarized_messages > 0:
                    st.session_state.unsummarized_messages = 14 
                
                # By passing this directly, we avoid the double st.rerun() that ruins audio autoplay!
                auto_topic = current_subject

        st.sidebar.markdown("---")
        
        # WE READ THE TOGGLE STATE CONTINUOUSLY, AND SAVE IT INTO SESSION STATE
        voice_on = st.sidebar.toggle("🔊 Read Christine's answers out loud", key="voice_toggle_widget")
        
        # --- MASTERY PERCENTAGE TRACKER ---
        st.sidebar.divider()
        st.sidebar.markdown(f"### 🏆 {selected_topic} Brain Power")

        dossier_text = user_data["summary"] if user_data.get("summary") else ""
        safe_topic = re.escape(selected_topic)

        topic_words = re.findall(r'[A-Za-z0-9]+', selected_topic)
        if topic_words:
            fuzzy_pattern = r'[^A-Za-z0-9]*'.join([rf' {w} ' for w in topic_words])
            mastered_count = len(re.findall(rf'{fuzzy_pattern}[^\[]{{0,40}}?mastered', dossier_text, flags=re.IGNORECASE | re.DOTALL))
            gap_count = len(re.findall(rf'{fuzzy_pattern}[^\[]{{0,40}}?gap', dossier_text, flags=re.IGNORECASE | re.DOTALL))
        else:
            mastered_count = 0
            gap_count = 0

        total_tracked = mastered_count + gap_count

        if total_tracked > 0:
            mastery_percentage = int((mastered_count / total_tracked) * 100)
        else:
            mastery_percentage = 0

        st.sidebar.progress(mastery_percentage / 100.0)
        
        if mastery_percentage == 100 and st.session_state.get("celebrated_topic") != selected_topic:
            st.balloons() 
            st.session_state["celebrated_topic"] = selected_topic

        st.sidebar.metric(label=f"Topic Mastery", value=f"{mastery_percentage}%")
        st.sidebar.caption(f"**{mastered_count}** Mastered | **{gap_count}** Gaps in {selected_topic}")
        
        st.sidebar.markdown("---")
        
        st.sidebar.header("📸 Submit Work")
        image_action = st.sidebar.radio(
            "Step 1: What should Christine do?",
            [
                "Review my essay/paragraph (AQA Mark Scheme)", 
                "Socratic Extract Analysis (Guide me)", 
                "Blind Analysis Practice (Unseen Text)",
                "Help me upgrade my vocabulary/argument"
            ]
        )
        
        st.sidebar.caption("Step 2: Upload or snap your photo/document:")
        file_input = st.sidebar.file_uploader("Upload File", type=['png', 'jpg', 'jpeg', 'webp', 'pdf'])
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

        # --- THE DOCUMENT VAULT UI ---
        st.sidebar.markdown("---")
        st.sidebar.header("🗄️ Document Vault")
        
        current_vault = user_data.get("file_vault", "")
        if current_vault:
            st.sidebar.success("✅ A document is saved in memory.")
            
            st.sidebar.toggle("📖 Use Vault Document in Chat", key="use_vault")
            
            with st.sidebar.expander("View Saved Document"):
                st.write(current_vault)
            if st.sidebar.button("🗑️ Clear Vault"):
                user_data["file_vault"] = ""
                save_current_student(username, user_data)
                st.session_state.use_vault = False
                st.rerun()
                
        elif file_input or st.session_state.captured_image:
            st.sidebar.info("Upload detected. Do you want Christine to memorize this so you don't have to upload it next time?")
            if st.sidebar.button("💾 Memorize Document"):
                with st.spinner("Extracting text to Vault..."):
                    try:
                        extracted_text = ""
                        
                        vault_model = genai.GenerativeModel(model_name=PRIMARY_MODEL)
                        prompt = "Extract and transcribe all the text, questions, and content from this document accurately."
                        
                        if file_input and file_input.name.lower().endswith('.pdf'):
                            pdf_part = {"mime_type": "application/pdf", "data": file_input.getvalue()}
                            resp = vault_model.generate_content([prompt, pdf_part])
                            extracted_text = resp.text
                        else:
                            if file_input: file_input.seek(0)
                            active_img = st.session_state.captured_image if st.session_state.captured_image else Image.open(file_input)
                            resp = vault_model.generate_content([prompt, active_img])
                            extracted_text = resp.text
                            
                        if not extracted_text.strip():
                            st.sidebar.error("Error: The AI could not extract any text from this file.")
                        else:
                            if len(extracted_text) > 35000:
                                extracted_text = extracted_text[:35000] + "\n\n[SYSTEM WARNING: Document reached the maximum database size. The end of the document was truncated.]"
                                
                            user_data["file_vault"] = extracted_text
                            save_current_student(username, user_data)
                            st.session_state.use_vault = True
                            st.sidebar.success("Saved to Vault instantly! You can close the file now.")
                            st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"Error saving to Vault: {e}")

        # --- ACTIVE AUTO-DOSSIER ---
        if st.session_state.unsummarized_messages >= 14:
            with st.spinner("Christine is organizing her notes..."):
                try:
                    grab_count = st.session_state.unsummarized_messages
                    recent_chat = str(user_data["history"][-grab_count:]) 
                    
                    memory_prompt = f'''
                    You are an expert teacher maintaining a highly compressed, long-term dossier on a student.
                    CURRENT DOSSIER: {user_data.get('summary', '')}
                    RECENT CHAT: {recent_chat}
                    
                    TASK: Update the CURRENT DOSSIER with new insights from the RECENT CHAT.
                    
                    CRITICAL RULES:
                    1. PRESERVE ALL OTHER TOPICS: You MUST keep all existing tags and notes for OTHER subjects exactly as they appear in the CURRENT DOSSIER. DO NOT delete them!
                    2. MASTERED TAGS: Start new or updated lines with exact format: [{selected_topic}] MASTERED:
                    3. GAP TAGS: Start new or updated lines with exact format: [{selected_topic}] GAP:
                    4. PRUNE: If they master a previous GAP in {selected_topic}, delete that specific GAP tag. 
                    5. DOCUMENT PROGRESS: If they are working on a saved document, explicitly state which specific questions or paragraphs they have ALREADY finished.
                    '''
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

        # --- CHAT HISTORY & HISTORICAL PLAYBACK ---
        for i, msg in enumerate(user_data["history"]):
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])
                
                # Check directly from session state if voice toggle is currently ON
                is_voice_enabled = st.session_state.get("voice_toggle_widget", False)
                
                # Play audio if history button clicked
                if role_display == "assistant" and is_voice_enabled:
                    if st.button("🔊 Play Voice", key=f"btn_hist_{i}"):
                        clean_speech = clean_text_for_speech(msg["content"])
                        if clean_speech:
                            with st.spinner("🎙️ Loading audio..."):
                                audio_bytes = generate_audio_bytes(clean_speech)
                                if audio_bytes:
                                    st.audio(audio_bytes, format='audio/mp3', autoplay=True)

        # --- INPUT & PROCESSING ---
        st.markdown("""
            <style>
            [data-testid="stHeader"] {
                position: fixed !important;
                top: 0 !important;
                transform: none !important;
                z-index: 99999 !important;
            }
            [data-testid="stAudioInput"] { 
                position: fixed; 
                bottom: 115px; 
                z-index: 999; 
            }
            .block-container { padding-bottom: 180px !important; } 
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

        if "auto_submit_topic" in st.session_state:
            auto_topic = st.session_state.pop("auto_submit_topic")
        
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
            pdf_part = None
            if has_image:
                try:
                    if file_input: file_input.seek(0)
                    
                    if not isinstance(active_image, Image.Image) and active_image.name.lower().endswith('.pdf'):
                        pdf_part = {"mime_type": "application/pdf", "data": active_image.getvalue()}
                        current_turn_content.append(pdf_part)
                    else:
                        pil_image = active_image if isinstance(active_image, Image.Image) else Image.open(active_image)
                        current_turn_content.append(pil_image)
                    
                    if image_action == "Review my essay/paragraph (AQA Mark Scheme)":
                        action_prompt = '''SYSTEM OVERRIDE: Act as a strict AQA Examiner. Do NOT rewrite the essay. Tell me which AOs (AO1, AO2, AO3) I am hitting, find the weakest sentence, and ask a Socratic question to force me to elevate it.'''
                    elif image_action == "Socratic Extract Analysis (Guide me)":
                        action_prompt = "SYSTEM OVERRIDE: Analyze this extract. Do not give me answers. Ask the first Socratic question about the writer's methods to begin analysis."
                    elif image_action == "Blind Analysis Practice (Unseen Text)":
                        action_prompt = '''SYSTEM OVERRIDE: Treat this as an AQA 'Unseen' text. Give me ZERO context. Ask a question forcing me to build a literary map from scratch based only on the language.'''
                    elif image_action == "Help me upgrade my vocabulary/argument":
                        action_prompt = "SYSTEM OVERRIDE: Help me move away from basic PEEL paragraphs. Ask me a highly perceptive question about the overarching theme."
                    else:
                        action_prompt = "SYSTEM OVERRIDE: Please analyze the attached material."
                        
                    file_label = "📄 Attached PDF" if pdf_part else "📸 Attached Image"
                    display_text += f"\n\n[{file_label}: {action_prompt}]"
                    st.session_state.last_processed_file_id = file_id
                except Exception as e:
                    st.error(f"Error processing file: {e}")
                    
            with st.chat_message("user"):
                if auto_topic: st.markdown(f"*(Switched topic to {auto_topic})*")
                if has_text: st.markdown(user_text)
                if has_image:
                    if pil_image:
                        st.image(pil_image, caption="Work for Review")
                    elif pdf_part:
                        st.markdown(f"📄 **PDF Document Uploaded:** `{active_image.name}`")
                if has_audio: st.audio(user_audio) 
            
            user_data["history"].append({"role": "user", "content": display_text})

            # --- SMART MEMORY OVERRIDE FIX: STICKY UPLOADS ---
            raw_history = [msg for msg in user_data["history"][:-1] if msg.get("content")]
            MAX_HISTORY = 10
            
            if len(raw_history) > MAX_HISTORY:
                pinned_context = raw_history[:2]
                recent_context = raw_history[-8:]
                
                middle_context = raw_history[2:-8]
                override_msg = None
                for msg in reversed(middle_context):
                    if "SYSTEM OVERRIDE" in msg.get("content", ""):
                        override_msg = msg
                        break 
                        
                if override_msg:
                    optimized_raw_history = pinned_context + [override_msg] + recent_context
                else:
                    optimized_raw_history = pinned_context + recent_context
            else:
                optimized_raw_history = raw_history
                
            chat_history = convert_history_for_gemini(optimized_raw_history)

            # --- AI GENERATION ---
            try:
                is_vault_active = st.session_state.get("use_vault", False)
                has_vault = bool(user_data.get("file_vault", "").strip())
                active_vault_content = user_data.get("file_vault", "") if is_vault_active else ""
                
                system_instruction = get_system_instruction(
                    user_data["age"], 
                    current_subject, 
                    user_data["summary"], 
                    file_vault=active_vault_content,
                    has_hidden_vault=(has_vault and not is_vault_active)
                )
                
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
                        
                        # Generate audio continuously in the SAME pass for the new message
                        is_voice_enabled_now = st.session_state.get("voice_toggle_widget", False)
                        if is_voice_enabled_now:
                            clean_speech = clean_text_for_speech(answer)
                            if clean_speech: 
                                with st.spinner("🎙️ Generating voice..."):
                                    audio_bytes = generate_audio_bytes(clean_speech)
                                if audio_bytes:
                                    st.audio(audio_bytes, format='audio/mp3', autoplay=True)
                
                user_data["history"].append({"role": "model", "content": answer})
                save_current_student(username, user_data)
                st.session_state.unsummarized_messages += 2

                if st.session_state.captured_image:
                    st.session_state.captured_image = None

                # --- THE INACTIVITY TIMER ACTIVATION FIX ---
                if 'dossier_timer' in st.session_state and st.session_state.dossier_timer.is_alive():
                    st.session_state.dossier_timer.cancel()
                    
                st.session_state.dossier_timer = threading.Timer(
                    300.0, 
                    background_dossier_save, 
                    args=[username, str(optimized_raw_history), selected_topic]
                )
                st.session_state.dossier_timer.start()

            except Exception as e:
                 st.error(f"Connection Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
