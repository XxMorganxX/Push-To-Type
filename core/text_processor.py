import threading
from collections import deque
from typing import Optional, Callable, Deque
import time


class TextProcessor:
    """
    Handles real-time text streaming with thread-safe buffering and processing.
    """
    
    def __init__(self, max_buffer_size: int = 1000, processing_interval: float = 0.1):
        """
        Initialize the text processor.
        
        Args:
            max_buffer_size: Maximum number of text chunks to buffer
            processing_interval: Time between processing cycles in seconds
        """
        self.max_buffer_size = max_buffer_size
        self.processing_interval = processing_interval
        
        # Thread-safe text buffer
        self.text_buffer: Deque[str] = deque(maxlen=max_buffer_size)
        self.buffer_lock = threading.Lock()
        
        # Processing state
        self.processing_thread: Optional[threading.Thread] = None
        self.stop_processing = threading.Event()
        self.text_callback: Optional[Callable[[str], None]] = None
        
        # Accumulated text for partial transcripts
        self.accumulated_text = ""
        self.last_final_text = ""
        
    def start(self, text_callback: Callable[[str], None]):
        """
        Start the text processing thread.
        
        Args:
            text_callback: Function to call with processed text
        """
        self.text_callback = text_callback
        self.stop_processing.clear()
        
        self.processing_thread = threading.Thread(
            target=self._process_loop,
            daemon=True
        )
        self.processing_thread.start()
    
    def stop(self):
        """Stop the text processing thread."""
        self.stop_processing.set()
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)
    
    def add_text(self, text: str, is_final: bool = False):
        """
        Add text to the processing buffer.
        
        Args:
            text: Text to add
            is_final: Whether this is a final transcript
        """
        with self.buffer_lock:
            self.text_buffer.append((text, is_final))
    
    def _process_loop(self):
        """Main processing loop running in separate thread."""
        while not self.stop_processing.is_set():
            self._process_buffer()
            time.sleep(self.processing_interval)
    
    def _process_buffer(self):
        """Process all text in the buffer."""
        if not self.text_callback:
            return
            
        texts_to_process = []
        
        with self.buffer_lock:
            while self.text_buffer:
                texts_to_process.append(self.text_buffer.popleft())
        
        for text, is_final in texts_to_process:
            self._handle_text(text, is_final)
    
    def _handle_text(self, text: str, is_final: bool):
        """
        Handle individual text chunks with partial/final logic.
        
        Args:
            text: Text to handle
            is_final: Whether this is a final transcript
        """
        if is_final:
            # For final text, only output the new portion
            if text and text != self.last_final_text:
                # Calculate the delta between this final and the last
                if self.last_final_text and text.startswith(self.last_final_text):
                    delta = text[len(self.last_final_text):]
                else:
                    delta = text
                
                if delta.strip():
                    self.text_callback(delta)
                
                self.last_final_text = text
                self.accumulated_text = ""
        else:
            # For partial text, accumulate and process progressively
            if text and len(text) > len(self.accumulated_text):
                # Output only the new characters
                delta = text[len(self.accumulated_text):]
                if delta:
                    self.text_callback(delta)
                    self.accumulated_text = text
    
    def clear_buffer(self):
        """Clear the text buffer."""
        with self.buffer_lock:
            self.text_buffer.clear()
            self.accumulated_text = ""
            self.last_final_text = ""
    
    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        with self.buffer_lock:
            return len(self.text_buffer)
    
    def is_processing(self) -> bool:
        """Check if currently processing."""
        return self.processing_thread and self.processing_thread.is_alive()


class StreamingTextProcessor(TextProcessor):
    """
    Extended text processor with advanced streaming capabilities.
    """
    
    def __init__(self, max_buffer_size: int = 1000, 
                 processing_interval: float = 0.05,
                 word_delimiter: str = " "):
        """
        Initialize the streaming text processor.
        
        Args:
            max_buffer_size: Maximum number of text chunks to buffer
            processing_interval: Time between processing cycles
            word_delimiter: Character to use for word separation
        """
        super().__init__(max_buffer_size, processing_interval)
        self.word_delimiter = word_delimiter
        self.partial_word_buffer = ""
        
    def _handle_text(self, text: str, is_final: bool):
        """
        Handle text with word-boundary awareness.
        
        Args:
            text: Text to handle
            is_final: Whether this is a final transcript
        """
        if is_final:
            # Flush any partial word buffer
            if self.partial_word_buffer:
                self.text_callback(self.partial_word_buffer)
                self.partial_word_buffer = ""
            
            # Process final text
            super()._handle_text(text, is_final)
        else:
            # For partial text, try to maintain word boundaries
            if text and len(text) > len(self.accumulated_text):
                delta = text[len(self.accumulated_text):]
                
                # Add to partial buffer
                self.partial_word_buffer += delta
                
                # Check for complete words
                if self.word_delimiter in self.partial_word_buffer:
                    parts = self.partial_word_buffer.rsplit(self.word_delimiter, 1)
                    if len(parts) > 1:
                        complete_text = parts[0] + self.word_delimiter
                        self.text_callback(complete_text)
                        self.partial_word_buffer = parts[1]
                
                self.accumulated_text = text