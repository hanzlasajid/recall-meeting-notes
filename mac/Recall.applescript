-- Recall droplet. setup_mac.command compiles this into "Recall.app" next to the tool.
-- Drop recordings on the app, or double-click it to pick one. Progress shows in a Terminal window.

on run
	launchTool("")
end run

on open droppedItems
	set args to ""
	repeat with f in droppedItems
		set args to args & " " & quoted form of (POSIX path of f)
	end repeat
	launchTool(args)
end open

on launchTool(args)
	set appPath to POSIX path of (path to me)
	if appPath ends with "/" then set appPath to text 1 thru -2 of appPath
	set toolDir to do shell script "dirname " & quoted form of appPath
	set cmd to "cd " & quoted form of toolDir & " && bash ./Recall.command" & args
	tell application "Terminal"
		activate
		do script cmd
	end tell
end launchTool
