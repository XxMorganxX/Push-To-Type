# Contributing to PTT Transcription

Thank you for considering contributing! 🎉

## Development Setup

1. Fork and clone the repo
2. Install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements-dev.txt
   ```
3. Make your changes
4. Run code formatter:
   ```bash
   black .
   ```
5. Test your changes thoroughly
6. Submit a pull request

## Pull Request Guidelines

- **One feature per PR** - Keep PRs focused
- **Describe your changes** - What and why
- **Test on macOS** - Ensure it works
- **Follow code style** - Use black for formatting
- **Update docs** - If adding features, update README.md

## Reporting Issues

When filing an issue, please include:

- macOS version
- Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant config.json settings
- Console output/logs

## Code Style

- Use `black` for Python formatting
- Use type hints where appropriate
- Add docstrings to public functions
- Keep functions focused and small

## Questions?

Open a discussion on GitHub!

