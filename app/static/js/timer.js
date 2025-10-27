
let timers = {};

function startTimer(taskId) {
    const start = Date.now();
    timers[taskId] = setInterval(() => {
        const elapsed = Math.floor((Date.now() - start) / 1000);
        const el = document.getElementById('timer-' + taskId);
        if (el) el.innerText = formatTime(elapsed);
    }, 1000);
}

function stopTimer(taskId) {
    clearInterval(timers[taskId]);
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}
