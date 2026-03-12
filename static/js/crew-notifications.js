/* Crew Mission Notifications - Browser + in-app toast notifications */
/* Depends on: crew-missions.js (crewMissionStatus, getTimeRemaining) */

// ═══════════════════════════════════════════════════════════════════
// MISSION COMPLETION NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════
let lastCaptainBusy = null;
let lastScientistBusy = null;
let notificationsEnabled = false;

// Request notification permission on first interaction
document.addEventListener('click', function requestNotifPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().then(perm => {
            notificationsEnabled = (perm === 'granted');
        });
    } else if ('Notification' in window && Notification.permission === 'granted') {
        notificationsEnabled = true;
    }
    document.removeEventListener('click', requestNotifPermission);
}, { once: true });

function checkMissionNotifications() {
    if (!crewMissionStatus) return;

    const cap = crewMissionStatus.captain;
    const sci = crewMissionStatus.scientist;

    // Captain completed (was busy, now ready to claim)
    if (cap?.busy) {
        const remaining = getTimeRemaining(cap.ends_at);
        if (remaining === 'Complete!') {
            showMissionReadyToast('captain', cap.target);
        }
    }
    // Captain just finished (was busy, now not)
    if (lastCaptainBusy === true && cap && !cap.busy) {
        showMissionCompleteNotification('captain');
    }
    lastCaptainBusy = cap?.busy || false;

    // Scientist completed (ready to claim)
    if (sci?.busy) {
        const remaining = getTimeRemaining(sci.ends_at);
        if (remaining === 'Complete!') {
            showMissionReadyToast('scientist', sci.target);
        }
    }
    // Scientist just finished
    if (lastScientistBusy === true && sci && !sci.busy) {
        showMissionCompleteNotification('scientist');
    }
    lastScientistBusy = sci?.busy || false;
}

function showMissionCompleteNotification(member) {
    const memberName = member === 'captain' ? 'Captain' : 'Scientist';

    // Browser notification (when tab is hidden)
    if (notificationsEnabled && document.hidden) {
        try {
            new Notification('Mission Complete!', {
                body: `${memberName} returned from trail mission`,
                icon: '/static/img/favicon.png',
                tag: `mission-${member}`
            });
        } catch (e) { /* ignore */ }
    }

    // In-app toast
    if (typeof showToast === 'function') {
        showToast(`${memberName} returned! +XP earned, trail improved.`, 'success');
    }
}

let missionReadyShown = { captain: false, scientist: false };
function showMissionReadyToast(member, target) {
    if (missionReadyShown[member]) return;
    missionReadyShown[member] = true;

    const memberName = member === 'captain' ? 'Captain' : 'Scientist';

    // Browser notification
    if (notificationsEnabled && document.hidden) {
        try {
            new Notification(`${memberName} Ready!`, {
                body: `Mission to ${target || 'trail'} complete. Tap to claim.`,
                icon: '/static/img/favicon.png',
                tag: `ready-${member}`
            });
        } catch (e) { /* ignore */ }
    }

    // In-app toast
    if (typeof showToast === 'function') {
        showToast(`${memberName} mission complete! Tap "Claim Reward" to collect.`, 'success');
    }

    // Reset after 60 seconds
    setTimeout(() => { missionReadyShown[member] = false; }, 60000);
}

// Initialize last busy state on page load
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(() => {
        if (crewMissionStatus) {
            lastCaptainBusy = crewMissionStatus.captain?.busy || false;
            lastScientistBusy = crewMissionStatus.scientist?.busy || false;
        }
    }, 2000);
});

