#!/bin/bash
set -e

echo "🚀 Automated GitHub Repository Setup for Vak"
echo "============================================="
echo ""

# Try to infer username from email (common pattern: cnv1989 -> cnv1989)
GITHUB_USERNAME="${GITHUB_USERNAME:-cnv1989}"
REMOTE_TYPE="${REMOTE_TYPE:-https}"

echo "Using GitHub username: $GITHUB_USERNAME"
echo "Using remote type: $REMOTE_TYPE"
echo ""

# Check if remote already exists
if git remote get-url origin &>/dev/null; then
    echo "⚠️  Remote 'origin' already exists:"
    git remote get-url origin
    echo ""
    read -p "Do you want to update it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing remote."
        exit 0
    fi
    git remote remove origin
fi

if [ "$REMOTE_TYPE" = "ssh" ]; then
    REMOTE_URL="git@github.com:${GITHUB_USERNAME}/vak.git"
else
    REMOTE_URL="https://github.com/${GITHUB_USERNAME}/vak.git"
fi

echo "Adding remote: $REMOTE_URL"
git remote add origin "$REMOTE_URL"

echo ""
echo "✅ Remote added successfully!"
echo ""
echo "⚠️  IMPORTANT: Make sure you've created the repository on GitHub first!"
echo "   Go to: https://github.com/new"
echo "   Repository name: vak"
echo "   DO NOT initialize with README, .gitignore, or license"
echo ""
echo "Once the repository is created, press Enter to push..."
read

echo ""
echo "Pushing to GitHub..."
if git push -u origin main; then
    echo ""
    echo "🎉 Success! Your repository is now on GitHub:"
    echo "   https://github.com/${GITHUB_USERNAME}/vak"
else
    echo ""
    echo "❌ Push failed. Common reasons:"
    echo "   1. Repository doesn't exist on GitHub yet"
    echo "   2. Authentication failed (you may need to enter credentials)"
    echo "   3. Wrong username"
    echo ""
    echo "To fix:"
    echo "   1. Create the repo at https://github.com/new"
    echo "   2. Or update username: GITHUB_USERNAME=yourusername ./setup-github-auto.sh"
    exit 1
fi
