Launchpad Production Update Guide

1. Server layout
   C:\webapps\launchpad-private
   IIS reverse proxy / web.config
   WinSW service
   Waitress app service

2. Pre-update checks
   git status
   current branch
   local uncommitted changes
   backup location

3. Fetch and review
   git fetch origin main
   git diff --name-status HEAD..origin/main
   check protected files

4. Protected files
   service/Launchpad-private.exe
   service/launchpad-private.xml
   service/Launchpad-private.xml
   web.config
   .env

5. Safe merge process
   stash
   merge --no-commit
   restore protected files
   commit merge

6. Dependency update
   .\venv\Scripts\pip install -r requirements.txt

7. Service restart
   Restart-Service Launchpad-private

8. Log monitoring
   service\*.err.log
   service\*.out.log

9. Rollback
   git reset --hard previous_commit
   restore backup
   restart service