#!/bin/bash
set -e

echo "🚀 GitHub Repository Setup for Vak"
echo "===================================="
echo ""

# Check if remote already exists
if git remote get-url origin &>/dev/null; then
    echo "⚠️  Remote 'origin' already exists:"
    git remote get-url origin
    read -p "Do you want to update it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing remote."
        exit 0
    fi
    git remote remove origin
fi

echo "📝 Please provide your GitHub username"
echo "   (This is the part after github.com/ in your profile URL)"
echo "   Example: If your profile is https://github.com/johndoe, enter 'johndoe'"
echo ""
read -p "GitHub username: " GITHUB_USERNAME

if [ -z "$GITHUB_USERNAME" ]; then
    echo "❌ Error: GitHub username cannot be empty"
    exit 1
fi

echo ""
echo "Choose remote URL type:"
echo "1) HTTPS (recommended for first-time setup)"
echo "2) SSH (requires SSH keys configured)"
read -p "Enter choice (1 or 2): " URL_TYPE

if [ "$URL_TYPE" = "2" ]; then
    REMOTE_URL="git@github.com:${GITHUB_USERNAME}/vak.git"
else
    REMOTE_URL="https://github.com/${GITHUB_USERNAME}/vak.git"
fi

echo ""
echo "Adding remote: $REMOTE_URL"
git remote add origin "$REMOTE_URL"

echo ""
echo "✅ Remote added successfully!"
echo ""
echo "Next steps:"
echo "1. Make sure you've created the repository on GitHub:"
echo "   https://github.com/new"
echo "   Repository name: vak"
echo "   DO NOT initialize with README, .gitignore, or license"
echo ""
read -p "2. Press Enter when you've created the repository on GitHub..."

echo ""
echo "Pushing to GitHub..."
git push -u origin main

echo ""
echo "🎉 Success! Your repository is now on GitHub:"
echo "   https://github.com/${GITHUB_USERNAME}/vak"
