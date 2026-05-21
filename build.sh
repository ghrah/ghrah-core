#!/usr/bin/env bash
set -euo pipefail

echo "Building wheel package for ghrah..."

# 清理旧的构建产物
rm -rf dist/

# 使用 uv 构建 wheel
uv build --wheel

echo "Build complete! Output:"
ls -lh dist/