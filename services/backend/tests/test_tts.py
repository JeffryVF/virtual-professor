"""Tests for TTS voice/language selection (female Edge-TTS voices)."""

from unittest.mock import patch

from services import tts
from services.tts import detect_language, resolve_language, _voice_for


class TestDetectLanguage:
    """ES/EN heuristic detection used for 'both' professors."""

    def test_spanish_with_accents(self):
        """GIVEN Spanish text with accented characters
        THEN detect_language returns 'es'.
        """
        assert detect_language("Cómo estás? Qué es la derivada?") == "es"

    def test_spanish_stopwords(self):
        """GIVEN Spanish text without accents
        THEN detect_language returns 'es' via stopword counts.
        """
        assert detect_language("Hola que sabes de calculo?") == "es"

    def test_english_stopwords(self):
        """GIVEN English text
        THEN detect_language returns 'en'.
        """
        assert detect_language("What can you teach about calculus?") == "en"

    def test_asymmetric_split_scores_es(self):
        """GIVEN text mixing ES and EN tokens so ES wins the count
        THEN detect_language returns 'es'.
        """
        assert detect_language("hola como esta el clima y que es xyz") == "es"


class TestResolveLanguage:
    """Mapping of professor language values to a TTS language."""

    def test_explicit_es_passthrough(self):
        assert resolve_language("es", "Hello what is that?") == "es"

    def test_explicit_en_passthrough(self):
        assert resolve_language("en", "Hola que tal?") == "en"

    def test_both_delegates_to_heuristic(self):
        assert resolve_language("both", "Hola profesora") == "es"
        assert resolve_language("both", "Hello professor") == "en"

    def test_both_with_enum_value(self):
        """GIVEN an enum-like object whose .value is 'both'
        THEN it is unwrapped and delegated to the heuristic.
        """
        assert resolve_language(type("Lang", (), {"value": "both"})(), "what is it") == "en"


class TestVoiceFor:
    """Female Edge-TTS voice selection per language."""

    def test_spanish_uses_female_elvira(self):
        with patch("services.tts.settings") as mock_settings:
            mock_settings.edge_tts_voice_es = "es-ES-ElviraNeural"
            mock_settings.edge_tts_voice_en = "en-US-JennyNeural"
            assert _voice_for("es", None) == "es-ES-ElviraNeural"

    def test_english_uses_female_jenny(self):
        with patch("services.tts.settings") as mock_settings:
            mock_settings.edge_tts_voice_en = "en-US-JennyNeural"
            assert _voice_for("en", None) == "en-US-JennyNeural"

    def test_explicit_voice_wins(self):
        with patch("services.tts.settings") as mock_settings:
            mock_settings.edge_tts_voice_en = "en-US-JennyNeural"
            assert _voice_for("en", "es-ES-ElviraNeural") == "es-ES-ElviraNeural"

    def test_unknown_language_defaults_to_english(self):
        with patch("services.tts.settings") as mock_settings:
            mock_settings.edge_tts_voice_en = "en-US-JennyNeural"
            assert _voice_for("fr", None) == "en-US-JennyNeural"