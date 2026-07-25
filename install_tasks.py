# -*- coding: utf-8 -*-
"""Windows Task Scheduler installer for TikTok automation."""
import os, sys, subprocess, ctypes, tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
bat_path = os.path.join(script_dir, "run_sea.bat")

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def create_task(name, hour, minute):
    xml = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TikTok SEA product research - %s</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2025-01-01T%02d:00:00</StartBoundary>
      <Repetition>
        <Interval></Interval>
        <Duration></Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "%s"</Arguments>
      <WorkingDirectory>%s</WorkingDirectory>
    </Exec>
  </Actions>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <Enabled>true</Enabled>
    <AllowStartOnBatteries>true</AllowStartOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
</Task>""" % (name, hour, bat_path, script_dir)

    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-16")
    fp.write(xml)
    fp.close()

    cmd = 'schtasks /Create /TN "TikTokAuto\\%s" /XML "%s" /F' % (name, fp.name)
    r = subprocess.run(cmd, shell=True, capture_output=True)
    os.unlink(fp.name)
    return r.returncode == 0

print("=== TikTok Scheduled Task Installer ===\n")

if not is_admin():
    print("This tool needs Administrator privileges.")
    print()
    print("Please run as Administrator:")
    print("  1. Press Win + X, select 'Terminal (Admin)'")
    print("  2. Run:  python \"%s\"" % os.path.abspath(__file__))
    print()
    input("Press Enter to exit...")
    sys.exit(1)

if not os.path.exists(bat_path):
    print("ERROR: run_sea.bat not found at", bat_path)
    sys.exit(1)

tasks = [
    ("SEA 08:00", 8, 0),
    ("SEA 12:00", 12, 0),
    ("SEA 20:00", 20, 0),
]

# Clean old tasks first
for name, _, _ in tasks:
    subprocess.run('schtasks /Delete /TN "TikTokAuto\\%s" /F' % name,
                   shell=True, capture_output=True)

ok = 0
for name, hour, minute in tasks:
    if create_task(name, hour, minute):
        print("  [OK] %s (%02d:00)" % (name, hour))
        ok += 1
    else:
        print("  [FAIL] %s" % name)

print("\nDone: %d/%d tasks created" % (ok, len(tasks)))
input("Press Enter to exit...")
