"""Shared validation for Google Drive/Workspace file references."""
# Drive can return native editor links for saved prompts and notebooks too.
GOOGLE_FILE_URL_PATTERN = r'^https://(?:(?:drive|docs|sites|aistudio)\.google\.com|colab\.research\.google\.com)/'
MOBILE_FILE_URL_PATTERN = r'^(?:jarvis-local://file/[A-Za-z0-9_-]+$|https://(?:(?:drive|docs|sites|aistudio)\.google\.com|colab\.research\.google\.com)/)'
