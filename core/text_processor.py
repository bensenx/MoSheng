"""Post-processing for ASR output: filler word removal and punctuation normalization."""
import re

# Chinese punctuation character class
_PUNCT = r'[，。！？；：、,.!?;:]'

# ── Filler patterns ──────────────────────────────────────────────────────────

# Standalone utterances that should produce no output
_RE_STANDALONE = re.compile(
    r'^[\s]*[嗯呃哦唔啊哎呦]*[，,、\s]*[嗯呃哦唔啊哎呦，,、\s]*[\s]*$'
)

# Stuttering / repeated filler phrases (always remove)
_RE_STUTTER = re.compile(
    r'(那个|然后|就是|这个){2,}'
)

# Clause-opener fillers: at start of text or after punctuation
_RE_CLAUSE_OPENER = re.compile(
    r'(^|(?<=[，。！？；：、,.!?;:]))\s*就是说[，,]?\s*'
)

# Single-char particles at start, end, or sandwiched between punctuation
_RE_PARTICLE_START = re.compile(r'^[嗯呃哦唔啊呦]+[，,]?\s*')
_RE_PARTICLE_END = re.compile(r'\s*[，,]?[嗯呃哦唔啊呦]+$')
_RE_PARTICLE_BETWEEN = re.compile(r'(?<=[，。！？；：、,.!?;:])\s*[嗯呃哦唔啊呦]+\s*(?=[，。！？；：、,.!?;:])')

# Interjections at start or end only
_RE_INTERJECTION_START = re.compile(r'^(哎呀|哎哟|哎|呐)[，,]?\s*')
_RE_INTERJECTION_END = re.compile(r'\s*[，,]?(哎呀|哎哟|哎|呐)$')

# End-of-utterance softeners (trailing only)
_RE_SOFTENER_END = re.compile(r'[啦嘛呗]+$')

# ── English filler patterns ───────────────────────────────────────────────────

# Standalone English filler utterances (entire text is just a filler)
_RE_EN_STANDALONE = re.compile(
    r'^[\s]*(um+|uh+|hmm+|mm+|er+)[,.]?[\s]*$', re.IGNORECASE
)

# Filler at the very start of text, followed by comma or space
_RE_EN_FILLER_START = re.compile(
    r'^(um+|uh+|hmm+|mm+|er+)[,\s]+', re.IGNORECASE
)

# Filler sandwiched between commas mid-sentence
_RE_EN_FILLER_MID = re.compile(
    r',\s*(um+|uh+|hmm+|mm+|er+)\s*,', re.IGNORECASE
)

# ── Punctuation patterns ─────────────────────────────────────────────────────

# Duplicate commas
_RE_DOUBLE_COMMA = re.compile(r'[，,]{2,}')

# Leading/trailing comma artifacts after filler removal
_RE_LEADING_COMMA = re.compile(r'^[，,]\s*')
_RE_TRAILING_COMMA = re.compile(r'\s*[，,]$')

# Duplicate periods (non-trailing)
_RE_DOUBLE_PERIOD = re.compile(r'。{2,}')


def process_text(text: str, remove_fillers: bool = True, smart_punctuation: bool = True) -> str:
    """Process ASR output text, removing fillers and normalizing punctuation.

    Returns empty string if the text is pure filler with no meaningful content.
    Trailing periods (。 or .) are NOT stripped here — TextProcessor.process() handles
    deferred-period logic for smart punctuation.
    """
    if not text:
        return text

    t = text.strip()

    if remove_fillers:
        # English: check standalone filler first
        if _RE_EN_STANDALONE.match(t):
            return ""

        # Check for standalone Chinese filler utterance
        if _RE_STANDALONE.match(t):
            return ""

        # English: remove filler at start and mid-sentence
        t = _RE_EN_FILLER_START.sub('', t)
        t = _RE_EN_FILLER_MID.sub(',', t)

        # Remove stuttering repeated phrases
        t = _RE_STUTTER.sub('', t)

        # Remove clause-opener fillers
        t = _RE_CLAUSE_OPENER.sub(r'\1', t)

        # Remove end-of-utterance softeners
        t = _RE_SOFTENER_END.sub('', t)

        # Remove interjections at boundaries
        t = _RE_INTERJECTION_START.sub('', t)
        t = _RE_INTERJECTION_END.sub('', t)

        # Remove single-char particles
        t = _RE_PARTICLE_BETWEEN.sub('，', t)
        t = _RE_PARTICLE_START.sub('', t)
        t = _RE_PARTICLE_END.sub('', t)

    if smart_punctuation:
        # Collapse duplicate periods (internal only; trailing period handled by TextProcessor)
        t = _RE_DOUBLE_PERIOD.sub('。', t)

    if remove_fillers:
        # Clean up comma artifacts from filler removal
        t = _RE_DOUBLE_COMMA.sub('，', t)
        t = _RE_LEADING_COMMA.sub('', t)
        t = _RE_TRAILING_COMMA.sub('', t)

    return t.strip()


class TextProcessor:
    """Stateful wrapper for text processing with deferred-period logic."""

    def __init__(self, remove_fillers: bool = True, smart_punctuation: bool = True):
        self._remove_fillers = remove_fillers
        self._smart_punctuation = smart_punctuation
        self._pending_period: str = ""  # '。' or '.' or '' — from previous process() call

    def update(self, remove_fillers: bool, smart_punctuation: bool) -> None:
        """Update settings without recreating the object."""
        self._remove_fillers = remove_fillers
        self._smart_punctuation = smart_punctuation

    def reset_session(self) -> None:
        """Call at recording start. Clears deferred period so no cross-session carryover."""
        self._pending_period = ""

    @property
    def pending_period(self) -> str:
        """The period character ('。' or '.') deferred from the last processed segment, or ''."""
        return self._pending_period

    def consume_pending_period(self) -> str:
        """Returns and clears the pending period. Call after session end to inject it."""
        p = self._pending_period
        self._pending_period = ""
        return p

    def process_simple(self, text: str) -> str:
        """Process without deferred-period logic. For PTT mode where each recording is standalone."""
        return process_text(text, self._remove_fillers, self._smart_punctuation)

    def process(self, text: str) -> str:
        """Process text with current settings, applying deferred-period logic."""
        result = process_text(text, self._remove_fillers, self._smart_punctuation)

        if not self._smart_punctuation:
            # Smart punct off: no period deferral, pass through as-is
            return result

        if not result:
            # Pure filler (empty result): keep existing pending period unchanged
            return result

        # Strip trailing period and remember it
        new_pending = ""
        if result.endswith('。'):
            result = result[:-1]
            new_pending = '。'
        elif result.endswith('.'):
            result = result[:-1]
            new_pending = '.'

        # Prepend comma from previous segment's deferred period (if any)
        if self._pending_period and result:
            result = '，' + result

        self._pending_period = new_pending
        return result
