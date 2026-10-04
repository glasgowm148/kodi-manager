#!/system/bin/sh
# Called by Kodi under its own Android UID. Wait for saved settings, stopped
# services and unloaded skin. Stop before NVIDIA's driver/static teardown;
# Android releases the remaining process/display resources after SIGKILL.
pid=$1
expected_start=$2
log=$3
offset=$4
result=$5
case "$pid:$expected_start:$offset" in *[!0-9:]*|'') exit 1;; esac
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
started=0
saved=0
stopped=0
buffer=
i=0
while [ "$i" -lt 1500 ]; do
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
                *' info <general>: Stopping the application...') started=1;;
                *' info <general>: Saving skin settings') [ "$started" = 1 ] && saved=1;;
                *' info <general>: Application stopped')
                    [ "$started" = 1 ] && [ "$saved" = 1 ] && stopped=1;;
                *' info <general>: Unloaded skin')
                    [ "$stopped" = 1 ] && finish_exit saved_services_skin_cleanup_completed;;
                *' info <general>: unload sections')
                    [ "$stopped" = 1 ] && finish_exit saved_window_cleanup_completed;;
            esac
        done
    fi
    /system/bin/toybox usleep 20000
    i=$((i+1))
done
exit 0
