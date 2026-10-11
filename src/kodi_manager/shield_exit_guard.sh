#!/system/bin/sh
# Called by Kodi under its own Android UID. Wait for saved settings, stopped
# services and unloaded skin. Stop before NVIDIA's driver/static teardown;
# Android releases the remaining process/display resources after SIGKILL.
# Also end an exit that stalls after Kodi saved its settings and skin settings
# ("Stopping all") but never reaches "Application stopped": a hang there
# otherwise needs a force-stop. Progress is traced on stderr for diagnosis.
pid=$1
expected_start=$2
log=$3
offset=$4
result=$5
# Polls (each at least 20 ms) allowed between "Stopping all" and the exit.
stall_limit=${6:-3000}
case "$pid:$expected_start:$offset:$stall_limit" in *[!0-9:]*|'') exit 1;; esac
[ "$pid" -gt 1 ] || exit 1
finish_exit() {
    reason=$1
    # Recheck the live parent relationship immediately before signalling.
    IFS= read -r proc_stat < /proc/self/stat || exit 0
    proc_fields=${proc_stat##*) }; set -- $proc_fields
    [ "$2" = "$pid" ] || exit 0
    printf '{"result":"%s","pid":%s,"start_tick":"%s"}\n' "$reason" "$pid" "$expected_start" > "$result"
    kill -KILL "$pid" || exit 1
    exit 0
}
trace() {
    printf '%s %s\n' "$i" "$1" >&2
}
started=0
saved=0
stop_all=0
stopped=0
stall=0
buffer=
i=0
trace armed
# Normally give up after 1500 polls; once settings are saved and Kodi is
# stopping, keep watching until it exits or the stall limit ends it.
while [ "$i" -lt 1500 ] || [ "$stop_all" = 1 ]; do
    # Android hides another process's /proc entry even from this same-UID
    # child. Reading our own stat gives the live kernel parent relationship.
    # If Kodi dies, we are reparented; a reused numeric PID cannot match it.
    IFS= read -r proc_stat < /proc/self/stat || exit 0
    proc_fields=${proc_stat##*) }
    set -f
    set -- $proc_fields
    [ "$2" = "$pid" ] || exit 0
    size=$(/system/bin/toybox stat -c %s "$log") || exit 1
    [ "$size" -ge "$offset" ] || exit 1
    if [ "$size" -gt "$offset" ]; then
        chunk=$(/system/bin/toybox dd if="$log" bs=4096 skip="$offset" count="$((size-offset))" iflag=skip_bytes,count_bytes status=none; printf '.')
        chunk=${chunk%.}
        offset=$size
        buffer="$buffer$chunk"
        # Process complete lines in order, retaining any partial final line.
        newline='
'
        while case "$buffer" in *"$newline"*) true;; *) false;; esac; do
            line=${buffer%%"$newline"*}
            buffer=${buffer#*"$newline"}
            case "$line" in
                *' info <general>: Stopping the application...')
                    [ "$started" = 1 ] || trace started
                    started=1;;
                *' info <general>: Saving skin settings')
                    if [ "$started" = 1 ] && [ "$saved" = 0 ]; then saved=1; trace saved; fi;;
                *' info <general>: Stopping all')
                    if [ "$saved" = 1 ] && [ "$stop_all" = 0 ]; then stop_all=1; trace stopping_all; fi;;
                *' info <general>: Application stopped')
                    if [ "$started" = 1 ] && [ "$saved" = 1 ] && [ "$stopped" = 0 ]; then stopped=1; trace stopped; fi;;
                *' info <general>: Unloaded skin')
                    [ "$stopped" = 1 ] && finish_exit saved_services_skin_cleanup_completed;;
                *' info <general>: unload sections')
                    [ "$stopped" = 1 ] && finish_exit saved_window_cleanup_completed;;
            esac
        done
    fi
    if [ "$stop_all" = 1 ]; then
        stall=$((stall+1))
        if [ "$stall" -ge "$stall_limit" ]; then
            trace stalled
            if [ "$stopped" = 1 ]; then
                finish_exit saved_application_stopped_stalled
            fi
            finish_exit saved_stopping_all_stalled
        fi
    fi
    /system/bin/toybox usleep 20000
    i=$((i+1))
done
trace gave_up
exit 0
