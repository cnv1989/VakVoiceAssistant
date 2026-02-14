# GitHub Repository Setup Instructions

## Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Sign in with your GitHub account (cnv1989@gmail.com)
3. Repository name: `vak`
4. Description: `Voice Assistant Kit - Monorepo with client, Deepgram server, and infrastructure`
5. Choose Public or Private
6. **DO NOT** initialize with README, .gitignore, or license (we already have these)
7. Click "Create repository"

## Step 2: Push to GitHub

After creating the repository, GitHub will show you commands. Use these:

```bash
cd /Users/nag/Projects/vak

# Add the remote (replace YOUR_USERNAME with your GitHub username)
# You can find your username in the GitHub URL after creating the repo
git remote add origin https://github.com/YOUR_USERNAME/vak.git

# Or if you prefer SSH:
# git remote add origin git@github.com:YOUR_USERNAME/vak.git

# Push to GitHub
git push -u origin main
```

**Note:** If you're not sure of your GitHub username, you can:
- Check the URL after creating the repo (it will be https://github.com/USERNAME/vak)
- Or run: `git remote add origin https://github.com/cnv1989/vak.git` (if your username matches your email prefix)
- Or check your GitHub profile URL

## Alternative: Using GitHub CLI (if installed)

If you have GitHub CLI installed:

```bash
cd /Users/nag/Projects/vak
gh auth login
gh repo create vak --public --source=. --remote=origin --push
```

## Quick Setup Script

Run this script to help set up the remote (it will prompt for your username):

```bash
cd /Users/nag/Projects/vak
./setup-github.sh
```

## Verify

After pushing, verify at: https://github.com/YOUR_USERNAME/vak

You should see the main directories:
- VakClient/
- VakDeepGram/
- VakInfra/
