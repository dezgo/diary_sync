"""Generate a concise daily summary from a diary transcript using Claude."""

import os
import logging

import anthropic

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are summarising a personal video diary transcript. The speaker records a \
~10 minute daily monologue covering their day.

Write a concise summary (3-8 sentences) covering the key events, activities, \
thoughts, and feelings from the day. Use past tense and refer to the speaker \
as "Derek". Focus on what actually happened — skip filler, repetition, \
tangents, and small talk. Keep the tone warm and natural, not robotic or \
bullet-pointy."""

USER_PROMPT = "Here is today's diary transcript. Please summarise it:\n\n{transcript}"


def generate_summary(
    transcript_text: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str | None:
    """Generate a brief summary of a diary transcript using Claude.

    Args:
        transcript_text: The full transcript text to summarise.
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Model ID to use. Defaults to Haiku.

    Returns:
        The summary text, or None if generation failed.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        log.warning("No Anthropic API key configured — skipping summary generation")
        return None

    if not transcript_text or not transcript_text.strip():
        log.warning("Empty transcript — skipping summary generation")
        return None

    model = model or DEFAULT_MODEL

    try:
        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": USER_PROMPT.format(transcript=transcript_text),
                }
            ],
        )
        summary = message.content[0].text.strip()
        if not summary:
            log.warning("Claude returned an empty summary")
            return None

        log.info(f"Generated summary ({len(summary)} chars) using {model}")
        return summary

    except anthropic.AuthenticationError:
        log.error("Anthropic API key is invalid — skipping summary generation")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit — skipping summary generation")
        return None
    except Exception as e:
        log.error(f"Summary generation failed: {e}", exc_info=True)
        return None
