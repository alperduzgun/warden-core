"""Natural language chat message handler."""

from typing import Callable


async def handle_chat_message(
    message: str,
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Handle natural language chat messages.

    Args:
        message: User's message
        add_message: Function to add messages to chat
    """
    message_lower = message.lower()

    if any(word in message_lower for word in ["analyze", "check", "inspect", "review"]):
        response = """
🤖 **Warden:** I can help you analyze code!

To analyze a specific file, use:
`/analyze <file_path>`

Or to scan your entire project:
`/scan`

Would you like to try one of these commands?
        """
    elif any(word in message_lower for word in ["help", "how", "what", "commands"]):
        response = """
🤖 **Warden:** I'm here to help!

I can assist you with:
- 🔍 Code analysis and validation
- 🛡️ Security checks
- 🔧 Auto-fixing issues
- 📊 Project scanning

Type `/help` to see all available commands, or just tell me what you'd like to do!
        """
    elif any(word in message_lower for word in ["fix", "repair", "solve"]):
        response = """
🤖 **Warden:** I can help fix issues!

To auto-fix problems in a file, use:
`/fix <file_path>`

First, you might want to run `/analyze` or `/scan` to see what needs fixing.
        """
    else:
        response = f"""
🤖 **Warden:** I understand you said: "{message}"

I'm currently in command mode. Here are some things I can do:
- `/analyze <file>` - Check code quality
- `/scan` - Scan entire project
- `/status` - Show session info
- `/help` - See all commands

What would you like me to do?
        """

    add_message(response.strip(), "assistant-message", True)
