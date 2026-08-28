import os
import base64
from gtts import gTTS
import tempfile

def text_to_speech(text):
    """
    Convert text to speech and return HTML audio element
    """
    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_filename = fp.name
            
        # Generate speech
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(temp_filename)
        
        # Read the audio file and encode to base64
        with open(temp_filename, "rb") as audio_file:
            audio_bytes = audio_file.read()
        
        # Clean up the temporary file
        os.unlink(temp_filename)
        
        # Encode to base64 for HTML audio element
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        # Create HTML audio element
        audio_html = f'<audio autoplay controls><source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3"></audio>'
        
        return audio_html
    except Exception as e:
        return f"Error generating speech: {str(e)}"