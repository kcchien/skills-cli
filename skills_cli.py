#!/usr/bin/env python3
"""
Skills CLI - Cross-platform CLI for managing Claude Code skills

This is the entry point script. The actual implementation is in the skills_cli package.

Usage:
    python skills_cli.py <command> [options]
    skills-cli <command> [options]  # if installed

For help:
    python skills_cli.py --help
"""

import sys

from skills_cli import main

if __name__ == "__main__":
    sys.exit(main())
