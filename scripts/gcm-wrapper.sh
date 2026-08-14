#!/bin/bash
# 包装 Windows 版 Git Credential Manager，供 WSL 中的 git 调用
exec "/mnt/c/Program Files/Git/mingw64/bin/git-credential-manager.exe" "$@"
