import streamlit as st
import speech_recognition as sr
from streamlit_webrtc import webrtc_streamer, WebRtcMode
import queue
import threading
import numpy as np

def speech_to_text():
    """
    Capture speech from microphone and convert to text
    """
    # Create a recognizer instance
    r = sr.Recognizer()
    
    # Use microphone as source
    with sr.Microphone() as source:
        st.info("Listening... Speak now")
        # Adjust for ambient noise
        r.adjust_for_ambient_noise(source)
        # Listen for audio input
        audio = r.listen(source, timeout=5, phrase_time_limit=10)
        st.info("Processing speech...")
        
        try:
            # Use Google Speech Recognition to convert audio to text
            text = r.recognize_google(audio)
            return text
        except sr.UnknownValueError:
            return "Sorry, I couldn't understand what you said."
        except sr.RequestError:
            return "Sorry, speech recognition service is unavailable."
        except Exception as e:
            return f"Error: {str(e)}"

class AudioProcessor:
    def __init__(self):
        self.text_queue = queue.Queue()
        self.recognizer = sr.Recognizer()
        self.is_listening = False
        self.stop_listening = False
        
    def start_listening(self):
        """Start listening in a separate thread"""
        self.is_listening = True
        self.stop_listening = False
        threading.Thread(target=self._listen_loop).start()
        
    def stop_listening_process(self):
        """Stop the listening process"""
        self.stop_listening = True
        self.is_listening = False
        
    def _listen_loop(self):
        """Background listening loop"""
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source)
                
                while not self.stop_listening:
                    try:
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=10)
                        text = self.recognizer.recognize_google(audio)
                        self.text_queue.put(text)
                        # Stop after getting one result
                        self.stop_listening = True
                        self.is_listening = False
                    except sr.WaitTimeoutError:
                        continue
                    except sr.UnknownValueError:
                        continue
                    except Exception as e:
                        self.text_queue.put(f"Error: {str(e)}")
                        self.stop_listening = True
                        self.is_listening = False
        except Exception as e:
            self.text_queue.put(f"Microphone Error: {str(e)}")
            self.is_listening = False
            
    def get_text(self):
        """Get recognized text if available"""
        if not self.text_queue.empty():
            return self.text_queue.get()
        return None

# Initialize audio processor in session state
def get_audio_processor():
    if 'audio_processor' not in st.session_state:
        st.session_state.audio_processor = AudioProcessor()
    return st.session_state.audio_processor