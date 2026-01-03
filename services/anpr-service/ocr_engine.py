"""
OCR/ANPR Engine using EasyOCR.
Recognizes license plates from cropped images.
"""
import easyocr
import cv2
import numpy as np
import re
from typing import List, Dict, Tuple, Optional
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import get_anpr_config

logger = get_logger(__name__)


class ANPREngine:
    """License plate recognition engine."""
    
    def __init__(self):
        """Initialize ANPR engine."""
        config = get_anpr_config()
        
        self.engine = config.engine
        self.languages = config.languages.split(',')
        self.min_confidence = config.min_confidence
        
        # Load plate format patterns
        anpr_config = config
        self.plate_patterns = [
            r"^[A-Z]{2,3}-[0-9]{3,4}$",
            r"^[0-9]{2}[A-Z]{2}[0-9]{4}$",
            r"^[A-Z]{3}[0-9]{3,4}$"
        ]
        
        # Initialize EasyOCR reader
        logger.info("initializing_ocr_reader", languages=self.languages)
        self.reader = easyocr.Reader(
            self.languages,
            gpu=True  # Use GPU if available
        )
        logger.info("ocr_reader_initialized")
    
    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess plate crop for better OCR.
        
        Args:
            image: Input plate crop
        
        Returns:
            Preprocessed image
        """
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        
        # Enhance contrast (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        
        # Threshold
        _, thresh = cv2.threshold(
            enhanced,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        
        return thresh
    
    def recognize(
        self,
        image_path: str
    ) -> Tuple[Optional[str], float, List[Dict]]:
        """
        Recognize plate text from image.
        
        Args:
            image_path: Path to plate crop image
        
        Returns:
            Tuple of (plate_text, confidence, raw_detections)
        """
        try:
            # Load image
            image = cv2.imread(image_path)
            if image is None:
                logger.error("failed_to_load_image", path=image_path)
                return None, 0.0, []
            
            # Preprocess
            processed = self.preprocess_image(image)
            
            # Run OCR
            results = self.reader.readtext(processed)
            
            if not results:
                logger.debug("no_text_detected", path=image_path)
                return None, 0.0, []
            
            # Extract text and confidence
            raw_detections = []
            for bbox, text, conf in results:
                raw_detections.append({
                    'text': text,
                    'confidence': float(conf),
                    'bbox': bbox
                })
            
            # Combine all text
            full_text = ' '.join([d['text'] for d in raw_detections])
            
            # Clean text (remove spaces, special chars)
            clean_text = self._clean_plate_text(full_text)
            
            # Calculate overall confidence
            avg_confidence = np.mean([d['confidence'] for d in raw_detections])
            
            # Validate format
            validated = self._validate_plate_format(clean_text)
            
            if validated and avg_confidence >= self.min_confidence:
                logger.info(
                    "plate_recognized",
                    text=clean_text,
                    confidence=avg_confidence,
                    validated=validated
                )
                return clean_text, float(avg_confidence), raw_detections
            else:
                logger.debug(
                    "plate_rejected",
                    text=clean_text,
                    confidence=avg_confidence,
                    validated=validated
                )
                return None, float(avg_confidence), raw_detections
        
        except Exception as e:
            logger.error(
                "recognition_failed",
                path=image_path,
                error=str(e),
                exc_info=True
            )
            return None, 0.0, []
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean and normalize plate text."""
        # Remove spaces
        text = text.replace(' ', '')
        
        # Convert to uppercase
        text = text.upper()
        
        # Remove common OCR errors
        text = text.replace('O', '0')  # O -> 0 where appropriate
        text = text.replace('I', '1')  # I -> 1 where appropriate
        
        # Remove special characters except hyphen
        text = re.sub(r'[^A-Z0-9-]', '', text)
        
        return text
    
    def _validate_plate_format(self, text: str) -> bool:
        """Validate plate text against known patterns."""
        for pattern in self.plate_patterns:
            if re.match(pattern, text):
                return True
        return False
