#!/bin/bash
# Andrew Sutherland <dr3wsuth3rland@gmail.com>

write_log () {
    echo "$@" >> $EV_BUILDLOG
}

fatal_error () {
    write_log $@
    exit 1
}

get_build_time () {
    declare -i h_ m_ s_ d_ f_=`date +%s` b_=$1
    local message=$2
    d_=$((f_-b_));h_=$((d_/3600))
    m_=$(($((d_-$((3600*h_))))/60));s_=$((d_-$((3600*h_))-$((60*m_))))
    write_log "$message ${h_}h ${m_}m ${s_}s"
}

run_build () {
    local target=$1 args="otapackage" buildstart=$(date +%s)
    local threads=$(($(cat /proc/meminfo | head -n1 | awk '{print $2}')/1000000))
    test "$target" = "passion" && args+=" systemupdatepackage"
    source build/envsetup.sh >/dev/null 2>&1 || fatal_error "ERROR:setenv failed for $target"
    breakfast $target >/dev/null 2>&1 || fatal_error "ERROR:breakfast failed for $target"
    make clobber >/dev/null 2>&1 || fatal_error "ERROR:clobbering failed for $target"
    make -j $threads $args >/dev/null 2>&1 || fatal_error "ERROR:build failed for $target"
    get_build_time $buildstart "INFO:Built $target in"
    return 0
}

run_build $EV_NIGHTLY_TARGET
