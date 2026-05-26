"""
Azure Pronunciation Assessment Wrapper
Azure 发音评估封装模块

Uses the azure-cognitiveservices-speech SDK to perform pronunciation
assessment on audio files. Returns detailed word-level and phoneme-level
scoring results.
"""

try:
    import azure.cognitiveservices.speech as speechsdk
    _AZURE_SDK_AVAILABLE = True
except ImportError:
    speechsdk = None
    _AZURE_SDK_AVAILABLE = False
import json
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from astrbot.api import logger


@dataclass
class PhonemeDetail:
    """Single phoneme assessment detail / 单个音素评估详情"""
    phoneme: str
    accuracy_score: float
    nbt_score: str  # 'None', 'Omission', 'Insertion', 'Mispronunciation'


@dataclass
class WordDetail:
    """Single word assessment detail / 单个单词评估详情"""
    word: str
    accuracy_score: float
    error_type: str  # 'None', 'Omission', 'Insertion', 'Mispronunciation'
    phonemes: List[PhonemeDetail] = field(default_factory=list)


@dataclass
class AssessmentResult:
    """
    Complete pronunciation assessment result / 完整的发音评估结果

    Contains overall scores, word-level details, and the raw JSON response
    from Azure Speech Services.
    """
    recognized_text: str
    accuracy_score: float
    fluency_score: float
    completeness_score: float
    prosody_score: float
    overall_score: float  # weighted average
    words: List[WordDetail] = field(default_factory=list)
    raw_json: dict = field(default_factory=dict)

    @property
    def problem_words(self) -> List[WordDetail]:
        """Words with accuracy below 60 / 准确度低于60的单词"""
        return [w for w in self.words if w.accuracy_score < 60 and w.error_type != 'None']

    @property
    def good_words(self) -> List[WordDetail]:
        """Words with accuracy above 85 / 准确度高于85的单词"""
        return [w for w in self.words if w.accuracy_score >= 85]


class PronunciationAssessmentError(Exception):
    """Custom exception for pronunciation assessment failures / 发音评估异常"""
    pass


class PronunciationAssessor:
    """
    Azure Speech SDK pronunciation assessment wrapper.
    Azure 语音 SDK 发音评估封装类

    Performs pronunciation assessment on audio files using Azure Cognitive
    Services Speech SDK. Supports word-level and phoneme-level granularity
    with prosody scoring.
    """

    # Score weights for overall score calculation (matching Azure defaults)
    # 各项评分权重（与 Azure 默认权重一致）
    WEIGHT_ACCURACY = 0.4
    WEIGHT_FLUENCY = 0.2
    WEIGHT_COMPLETENESS = 0.2
    WEIGHT_PROSODY = 0.2

    def __init__(self, subscription_key: str, region: str):
        """
        Initialize the assessor with Azure credentials.

        Args:
            subscription_key: Azure Speech Services subscription key
            region: Azure region (e.g., "eastasia", "eastus")
        """
        if not _AZURE_SDK_AVAILABLE:
            raise ImportError(
                "azure-cognitiveservices-speech 未安装。"
                "请运行: pip install azure-cognitiveservices-speech"
            )
        if not subscription_key or not subscription_key.strip():
            raise ValueError("Azure subscription key must not be empty")
        if not region or not region.strip():
            raise ValueError("Azure region must not be empty")

        self.subscription_key = subscription_key.strip()
        self.region = region.strip()

    async def assess(
        self,
        audio_path: str,
        reference_text: str,
        language: str = "en-US",
    ) -> AssessmentResult:
        """
        Perform pronunciation assessment on an audio file.
        对音频文件进行发音评估

        Runs the blocking Azure SDK call in a thread pool via asyncio.to_thread
        to avoid blocking the event loop.

        Args:
            audio_path: Path to WAV audio file (16kHz, 16-bit, mono recommended)
            reference_text: The expected text that should have been read
            language: Language code (en-US, en-GB, zh-CN, etc.)

        Returns:
            AssessmentResult with detailed scoring

        Raises:
            PronunciationAssessmentError: If assessment fails
        """
        if not reference_text or not reference_text.strip():
            raise ValueError("Reference text must not be empty")

        return await asyncio.to_thread(
            self._assess_sync, audio_path, reference_text, language
        )

    def _assess_sync(
        self,
        audio_path: str,
        reference_text: str,
        language: str,
    ) -> AssessmentResult:
        """
        Synchronous pronunciation assessment implementation.
        同步发音评估实现

        Steps:
        1. Create SpeechConfig with subscription and region
        2. Set speech_recognition_language
        3. Create PronunciationAssessmentConfig with reference text,
           HundredMark grading, Phoneme granularity, miscue enabled
        4. Enable prosody assessment via JSON config patching
        5. Create AudioConfig from the wav file
        6. Create SpeechRecognizer and apply pronunciation config
        7. Call recognize_once_async().get() to get recognition result
        8. Parse PronunciationAssessmentResult for overall scores
        9. Extract word-level and phoneme-level details from JSON response
        10. Build and return AssessmentResult
        """
        # --- Step 1 & 2: Speech config ---
        speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key,
            region=self.region,
        )
        speech_config.speech_recognition_language = language
        logger.info(
            f"[PronunciationAssessor] Created SpeechConfig for region={self.region}, "
            f"language={language}"
        )

        # --- Step 3: Pronunciation assessment config ---
        pronunciation_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True,
        )

        # --- Step 4: Enable prosody via JSON config patching ---
        # The SDK doesn't expose prosody as a direct parameter, so we patch
        # the underlying JSON configuration.
        try:
            pron_config_json = json.loads(pronunciation_config.to_json())
            pron_config_json["enableProsodyAssessment"] = True
            pronunciation_config = (
                speechsdk.PronunciationAssessmentConfig.from_json(
                    json.dumps(pron_config_json)
                )
            )
            logger.debug("[PronunciationAssessor] Prosody assessment enabled via JSON config")
        except Exception as e:
            # If prosody patching fails, continue without it — it's non-critical
            logger.warning(
                f"[PronunciationAssessor] Failed to enable prosody assessment: {e}. "
                "Continuing without prosody scoring."
            )

        # --- Step 5: Audio config ---
        try:
            audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
        except Exception as e:
            raise PronunciationAssessmentError(
                f"Failed to load audio file '{audio_path}': {e}"
            ) from e

        # --- Step 6: Create recognizer and apply pronunciation config ---
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        pronunciation_config.apply_to(recognizer)
        logger.info(
            f"[PronunciationAssessor] Starting assessment for audio: {audio_path}"
        )

        # --- Step 7: Perform recognition ---
        try:
            result = recognizer.recognize_once_async().get()
        except Exception as e:
            raise PronunciationAssessmentError(
                f"Speech recognition call failed: {e}"
            ) from e

        # --- Handle result status ---
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            error_msg = (
                f"Speech recognition canceled. Reason: {cancellation.reason}. "
                f"Error code: {cancellation.error_code}. "
                f"Error details: {cancellation.error_details}"
            )
            logger.error(f"[PronunciationAssessor] {error_msg}")
            raise PronunciationAssessmentError(error_msg)

        if result.reason == speechsdk.ResultReason.NoMatch:
            no_match_detail = result.no_match_details
            logger.warning(
                f"[PronunciationAssessor] No speech recognized. "
                f"Reason: {no_match_detail.reason}"
            )
            # Return a zeroed-out result so callers can handle gracefully
            return AssessmentResult(
                recognized_text="",
                accuracy_score=0.0,
                fluency_score=0.0,
                completeness_score=0.0,
                prosody_score=0.0,
                overall_score=0.0,
                words=[],
                raw_json={},
            )

        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            raise PronunciationAssessmentError(
                f"Unexpected result reason: {result.reason}"
            )

        # --- Step 8: Parse pronunciation assessment result ---
        pron_result = speechsdk.PronunciationAssessmentResult(result)

        accuracy_score = pron_result.accuracy_score or 0.0
        fluency_score = pron_result.fluency_score or 0.0
        completeness_score = pron_result.completeness_score or 0.0
        # Prosody score may not be available on all SDK versions
        prosody_score = getattr(pron_result, "prosody_score", None) or 0.0

        logger.info(
            f"[PronunciationAssessor] Overall scores — "
            f"accuracy={accuracy_score:.1f}, fluency={fluency_score:.1f}, "
            f"completeness={completeness_score:.1f}, prosody={prosody_score:.1f}"
        )

        # --- Step 9: Extract detailed JSON for word/phoneme-level info ---
        raw_json_str = result.properties.get(
            speechsdk.PropertyId.SpeechServiceResponse_JsonResult, "{}"
        )
        try:
            raw_json = json.loads(raw_json_str)
        except json.JSONDecodeError:
            logger.warning(
                "[PronunciationAssessor] Failed to parse detailed JSON response. "
                "Using SDK-level word details as fallback."
            )
            raw_json = {}

        words = self._parse_words_from_json(raw_json)

        # If JSON parsing yielded no words, fall back to SDK word list
        if not words:
            words = self._parse_words_from_sdk(pron_result)

        # --- Step 10: Compute overall weighted score ---
        overall_score = (
            accuracy_score * self.WEIGHT_ACCURACY
            + fluency_score * self.WEIGHT_FLUENCY
            + completeness_score * self.WEIGHT_COMPLETENESS
            + prosody_score * self.WEIGHT_PROSODY
        )

        return AssessmentResult(
            recognized_text=result.text or "",
            accuracy_score=accuracy_score,
            fluency_score=fluency_score,
            completeness_score=completeness_score,
            prosody_score=prosody_score,
            overall_score=round(overall_score, 1),
            words=words,
            raw_json=raw_json,
        )

    def _parse_words_from_json(self, raw_json: dict) -> List[WordDetail]:
        """
        Parse word-level and phoneme-level details from the raw Azure JSON response.
        从 Azure 原始 JSON 响应中解析单词级和音素级详情

        The JSON structure follows the Azure Speech Services response format:
        {
          "NBest": [{
            "Words": [{
              "Word": "hello",
              "PronunciationAssessment": {
                "AccuracyScore": 95.0,
                "ErrorType": "None"
              },
              "Phonemes": [{
                "Phoneme": "h",
                "PronunciationAssessment": {
                  "AccuracyScore": 98.0,
                  "NBestPhonemes": [...]
                }
              }, ...]
            }, ...]
          }]
        }
        """
        words: List[WordDetail] = []

        try:
            nbest_list = raw_json.get("NBest", [])
            if not nbest_list:
                return words

            # Use the first (best) recognition alternative
            best = nbest_list[0]
            word_entries = best.get("Words", [])

            for w_entry in word_entries:
                word_text = w_entry.get("Word", "")
                w_assessment = w_entry.get("PronunciationAssessment", {})
                w_accuracy = w_assessment.get("AccuracyScore", 0.0)
                w_error = w_assessment.get("ErrorType", "None")

                # Parse phonemes for this word
                phonemes: List[PhonemeDetail] = []
                phoneme_entries = w_entry.get("Phonemes", [])
                for p_entry in phoneme_entries:
                    p_text = p_entry.get("Phoneme", "")
                    p_assessment = p_entry.get("PronunciationAssessment", {})
                    p_accuracy = p_assessment.get("AccuracyScore", 0.0)
                    p_nbt = p_assessment.get("ErrorType", "None")
                    phonemes.append(
                        PhonemeDetail(
                            phoneme=p_text,
                            accuracy_score=float(p_accuracy),
                            nbt_score=str(p_nbt),
                        )
                    )

                words.append(
                    WordDetail(
                        word=word_text,
                        accuracy_score=float(w_accuracy),
                        error_type=str(w_error),
                        phonemes=phonemes,
                    )
                )

            logger.debug(
                f"[PronunciationAssessor] Parsed {len(words)} words from JSON response"
            )
        except (KeyError, TypeError, IndexError) as e:
            logger.warning(
                f"[PronunciationAssessor] Error parsing words from JSON: {e}"
            )
            words = []

        return words

    def _parse_words_from_sdk(
        self, pron_result: speechsdk.PronunciationAssessmentResult
    ) -> List[WordDetail]:
        """
        Fallback: parse word details from the SDK PronunciationAssessmentResult object.
        回退方案：从 SDK PronunciationAssessmentResult 对象中解析单词详情

        Used when the raw JSON response is unavailable or fails to parse.
        Phoneme-level detail is not available through this path.
        """
        words: List[WordDetail] = []

        try:
            sdk_words = pron_result.words
            if not sdk_words:
                return words

            for w in sdk_words:
                w_accuracy = 0.0
                w_error = "None"

                # Access word-level pronunciation assessment
                try:
                    w_accuracy = w.accuracy_score or 0.0
                except AttributeError:
                    pass
                try:
                    w_error = w.error_type or "None"
                except AttributeError:
                    pass

                # Attempt phoneme-level if available on SDK word object
                phonemes: List[PhonemeDetail] = []
                try:
                    if hasattr(w, "phonemes") and w.phonemes:
                        for p in w.phonemes:
                            phonemes.append(
                                PhonemeDetail(
                                    phoneme=getattr(p, "phoneme", ""),
                                    accuracy_score=float(
                                        getattr(p, "accuracy_score", 0.0)
                                    ),
                                    nbt_score="None",
                                )
                            )
                except Exception:
                    pass

                words.append(
                    WordDetail(
                        word=w.word or "",
                        accuracy_score=float(w_accuracy),
                        error_type=str(w_error),
                        phonemes=phonemes,
                    )
                )

            logger.debug(
                f"[PronunciationAssessor] Parsed {len(words)} words from SDK result"
            )
        except Exception as e:
            logger.warning(
                f"[PronunciationAssessor] Error parsing words from SDK result: {e}"
            )

        return words
