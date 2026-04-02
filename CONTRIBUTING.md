# Contributing to bunqer

Thank you for your interest in contributing to bunqer. This document outlines the process and guidelines for contributing.

## Getting Started

1. Fork the repository and clone your fork
2. Follow the [Quick Start](README.md#quick-start) guide to set up your development environment
3. Create a new branch for your work: `git checkout -b feature/your-feature`

## Development Workflow

- Run `task dev` to start both the API and UI in development mode
- Run `task lint` before committing to catch formatting and style issues
- Write clear, descriptive commit messages
- Keep pull requests focused — one feature or fix per PR

## Code Style

### Python (API)

- Follow PEP 8 conventions
- Use type hints for function signatures
- Format with ruff

### JavaScript (UI)

- Follow the existing Svelte 5 patterns in the codebase
- Use Tailwind CSS utility classes for styling
- Prefer small, composable components

## Pull Requests

1. Make sure your branch is up to date with `main`
2. Verify that linters pass: `task lint`
3. Write a clear PR description explaining **what** changed and **why**
4. Link any related issues

## Reporting Issues

- Use [GitHub Issues](../../issues) to report bugs or suggest features
- Include steps to reproduce for bug reports
- Check existing issues before opening a new one

## Code of Conduct

Be respectful and constructive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) code of conduct.

## License

By contributing to bunqer, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).
