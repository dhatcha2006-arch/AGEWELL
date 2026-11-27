// AGEWELL Senior Independence Portal - Main Client Script

document.addEventListener('DOMContentLoaded', () => {
  initVoiceAssistant();
  initAccessibilityControls();
  initNotificationPolling();
  initTheme();
});

// 1. Web Audio Synthesizer for alerts
function playTone(type) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    if (type === 'success') {
      osc.type = 'sine';
      osc.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
      osc.frequency.exponentialRampToValueAtTime(659.25, ctx.currentTime + 0.15); // E5
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
      osc.start();
      osc.stop(ctx.currentTime + 0.3);
    } else if (type === 'sos') {
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(440, ctx.currentTime + 0.25);
      gain.gain.setValueAtTime(0.5, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
      osc.start();
      osc.stop(ctx.currentTime + 0.5);
    }
  } catch(e) {
    console.log("AudioContext unavailable:", e);
  }
}

// 3. Senior Voice Assistant (Text to Speech)
function initVoiceAssistant() {
  const voiceBtn = document.getElementById('voice-assist-toggle');
  if (!voiceBtn) return;

  voiceBtn.addEventListener('click', () => {
    if (!('speechSynthesis' in window)) {
      alert("Speech synthesis is not supported in this browser.");
      return;
    }

    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      voiceBtn.innerHTML = '<i class="bi bi-volume-up-fill"></i> Read Reminders Aloud';
      return;
    }

    // Gather reminders text from page
    const reminderElements = document.querySelectorAll('[data-speakable]');
    let textToSpeak = "Hello! Here are your daily updates: ";
    
    if (reminderElements.length > 0) {
      reminderElements.forEach(el => {
        textToSpeak += el.innerText + ". ";
      });
    } else {
      textToSpeak += "You have no pending urgent alerts today. You are doing great!";
    }

    const utterance = new SpeechSynthesisUtterance(textToSpeak);
    utterance.rate = 0.9; // Slower, clearer cadence for seniors
    utterance.pitch = 1.0;
    
    voiceBtn.innerHTML = '<i class="bi bi-stop-circle-fill text-danger"></i> Stop Speaking';
    
    utterance.onend = () => {
      voiceBtn.innerHTML = '<i class="bi bi-volume-up-fill"></i> Read Reminders Aloud';
    };

    window.speechSynthesis.speak(utterance);
  });
}

// 4. Accessibility Mode Switches
function initAccessibilityControls() {
  const toggleSeniorMode = document.getElementById('toggle-senior-size');
  if (toggleSeniorMode) {
    toggleSeniorMode.addEventListener('click', () => {
      document.body.classList.toggle('senior-mode');
      const isBig = document.body.classList.contains('senior-mode');
      localStorage.setItem('agewell_senior_size', isBig ? '1' : '0');
    });
    if (localStorage.getItem('agewell_senior_size') === '1') {
      document.body.classList.add('senior-mode');
    }
  }
}

// 5. Notification polling
function initNotificationPolling() {
  const badge = document.getElementById('unread-notif-count');
  if (!badge) return;

  setInterval(() => {
    fetch('/api/notifications/unread-count')
      .then(res => res.json())
      .then(data => {
        if (data.count > 0) {
          badge.innerText = data.count;
          badge.classList.remove('d-none');
        } else {
          badge.classList.add('d-none');
        }
      })
      .catch(err => console.log('Notif poll err', err));
  }, 12000);
}

// 6. SOS Countdown & Escalation Simulator
function initSOSCountdown(secondsRemaining, escalationStep, totalSteps, isResponding = false) {
  const timerDisplay = document.getElementById('sos-countdown');
  const stepBadge = document.getElementById('escalation-step-badge');
  if (!timerDisplay) return;

  if (isResponding) {
    timerDisplay.innerText = "PAUSED";
    timerDisplay.classList.remove('text-warning', 'text-danger');
    timerDisplay.classList.add('text-success');
    return;
  }

  let left = secondsRemaining;
  if (left <= 0) {
    if (escalationStep >= totalSteps + 1) {
      timerDisplay.innerText = "Dispatch Active";
    } else {
      timerDisplay.innerText = "Escalated";
    }
    return;
  }

  const interval = setInterval(() => {
    if (left <= 0) {
      clearInterval(interval);
      timerDisplay.innerText = "Advancing to next contact...";
      setTimeout(() => {
        window.location.reload();
      }, 3000);
      return;
    }
    const mins = Math.floor(left / 60);
    const secs = left % 60;
    timerDisplay.innerText = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    left--;
  }, 1000);
}

// 7. Demo Account Fast Login Switcher
function fillDemoLogin(role, autoSubmit = false) {
  const emailInput = document.getElementById('login-email');
  const passInput = document.getElementById('login-password');
  if (!emailInput || !passInput) return;

  const credentials = {
    'senior': { email: 'senior@agewell.com', pass: 'password123' },
    'family': { email: 'family@agewell.com', pass: 'password123' },
    'doctor': { email: 'doctor@agewell.com', pass: 'password123' },
    'admin':  { email: 'admin@agewell.com',  pass: 'password123' }
  };

  const creds = credentials[role];
  if (!creds) return;

  emailInput.value = creds.email;
  passInput.value = creds.pass;

  if (typeof playTone === 'function') playTone('success');

  if (autoSubmit) {
    const form = emailInput.closest('form');
    if (form) form.submit();
  }
}

// 7. Dynamic Theme Switcher System
function initTheme() {
  const savedTheme = localStorage.getItem('agewell_theme') || 'forest';
  setAppTheme(savedTheme, false);
}

window.setAppTheme = function(themeName, save = true) {
  if (!themeName || themeName === 'forest') {
    document.documentElement.setAttribute('data-theme', 'forest');
  } else {
    document.documentElement.setAttribute('data-theme', themeName);
  }
  if (save) {
    localStorage.setItem('agewell_theme', themeName);
    if (typeof playTone === 'function') {
      playTone('success');
    }
  }
};

// Register PWA Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js').catch((err) => {
      console.debug('ServiceWorker registration skipped:', err);
    });
  });
}

// Periodic session heartbeat (every 5 minutes) to keep bedside tablet sessions alive
setInterval(async () => {
  try {
    await fetch('/api/session/heartbeat');
  } catch (err) {
    // Ignore network interruptions
  }
}, 300000);


