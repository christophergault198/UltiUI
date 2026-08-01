        // Escapes text before it is interpolated into an innerHTML template
        // string. Anything that ultimately originates from the printer
        // (system log lines, alert messages, etc.) must be escaped here
        // before being rendered, since it is not trusted input.
        function escapeHtml(value) {
            if (value === null || value === undefined) return '';
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        let statsInterval;
        let jobInterval;
        let printCoresInterval;
        let logInterval;
        let seenMessages = new Set();
        let flowInterval;
        let healthInterval;
        let printerIndicatorInterval;
        const MAX_FLOW_RATE = 5000;  // Maximum expected flow rate
        const MAX_HEATER_POWER = 255;  // Maximum heater power value
        const MAX_TEMP_HISTORY = 60; // Number of temperature points to show
        const tempHistory = {
            bed: { current: [], target: [], labels: [] },
            ext1: { current: [], target: [], labels: [] },
            ext2: { current: [], target: [], labels: [] }
        };
        const flowHistory = {
            ext0: { flow: [], power: [], labels: [] },
            ext1: { flow: [], power: [], labels: [] }
        };

        // SVG Gauge utilities
        function setTempGauge(svgId, arcId, value, maxValue) {
            const arc = document.getElementById(arcId);
            const pct = Math.min(value / maxValue, 1);
            const circumference = 2 * Math.PI * 80;
            const arcLength = circumference * 0.75;
            const offset = arcLength * (1 - pct);
            arc.style.strokeDasharray = `${arcLength - offset} ${circumference}`;
            let color;
            if (pct < 0.5) color = '#22c55e';
            else if (pct < 0.8) color = pct < 0.65 ? '#3b82f6' : '#f59e0b';
            else color = '#ef4444';
            arc.style.stroke = color;
        }

        function setMatGauge(arcId, fraction) {
            const arc = document.getElementById(arcId);
            const clamped = Math.min(Math.max(fraction, 0), 1);
            const circumference = 2 * Math.PI * 44;
            const offset = circumference * (1 - clamped);
            arc.style.strokeDasharray = `${circumference - offset} ${circumference}`;
            let color;
            if (clamped > 0.5) color = '#22c55e';
            else if (clamped > 0.2) color = '#f59e0b';
            else color = '#ef4444';
            arc.style.stroke = color;
        }

        function initTempGauges() {
            setTempGauge('bed-gauge', 'bed-gauge-arc', 0, 120);
            setTempGauge('ext1-gauge', 'ext1-gauge-arc', 0, 300);
            setTempGauge('ext2-gauge', 'ext2-gauge-arc', 0, 300);
        }

        function initMatGauges() {
            setMatGauge('ext0-mat-arc', 0);
            setMatGauge('ext1-mat-arc', 0);
        }

        // Initialize temperature charts
        function initTempCharts() {
            // Base chart options
            const baseChartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false,
                            drawBorder: false
                        }
                    },
                    y: {
                        display: true,
                        position: 'right',
                        beginAtZero: true,
                        suggestedMin: 0,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)',
                            drawBorder: false,
                            borderDash: [5, 5]
                        },
                        ticks: {
                            font: {
                                size: 10
                            },
                            padding: 5
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: false
                    }
                },
                elements: {
                    point: {
                        radius: 0,
                        hoverRadius: 0
                    },
                    line: {
                        tension: 0.4,
                        borderWidth: 1.5
                    }
                }
            };

            // Create specific options for each chart
            const bedChartOptions = {
                ...baseChartOptions,
                scales: {
                    ...baseChartOptions.scales,
                    y: {
                        ...baseChartOptions.scales.y,
                        suggestedMax: 120,  // Bed temperature max
                        ticks: {
                            ...baseChartOptions.scales.y.ticks,
                            stepSize: 20
                        }
                    }
                }
            };

            const extruderChartOptions = {
                ...baseChartOptions,
                scales: {
                    ...baseChartOptions.scales,
                    y: {
                        ...baseChartOptions.scales.y,
                        suggestedMax: 250,  // Extruder temperature max
                        ticks: {
                            ...baseChartOptions.scales.y.ticks,
                            stepSize: 50
                        }
                    }
                }
            };

            // Dark mode chart options
            const darkModeOptions = {
                scales: {
                    y: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)',
                            drawBorder: false,
                            borderDash: [5, 5]
                        },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.7)'
                        }
                    }
                }
            };

            // Bed temperature chart
            window.bedTempChart = new Chart(
                document.getElementById('bed-temp-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [
                            {
                                label: 'Current',
                                data: [],
                                borderColor: '#3B82F6',
                                backgroundColor: 'transparent',
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            },
                            {
                                label: 'Target',
                                data: [],
                                borderColor: '#9CA3AF',
                                backgroundColor: 'transparent',
                                borderDash: [5, 5],
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            }
                        ]
                    },
                    options: document.documentElement.classList.contains('dark') 
                        ? { ...bedChartOptions, scales: { ...bedChartOptions.scales, ...darkModeOptions.scales } }
                        : bedChartOptions
                }
            );

            // Extruder 1 temperature chart
            window.ext1TempChart = new Chart(
                document.getElementById('ext1-temp-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [
                            {
                                label: 'Current',
                                data: [],
                                borderColor: '#3B82F6',
                                backgroundColor: 'transparent',
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            },
                            {
                                label: 'Target',
                                data: [],
                                borderColor: '#9CA3AF',
                                backgroundColor: 'transparent',
                                borderDash: [5, 5],
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            }
                        ]
                    },
                    options: document.documentElement.classList.contains('dark')
                        ? { ...extruderChartOptions, scales: { ...extruderChartOptions.scales, ...darkModeOptions.scales } }
                        : extruderChartOptions
                }
            );

            // Extruder 2 temperature chart
            window.ext2TempChart = new Chart(
                document.getElementById('ext2-temp-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [
                            {
                                label: 'Current',
                                data: [],
                                borderColor: '#3B82F6',
                                backgroundColor: 'transparent',
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            },
                            {
                                label: 'Target',
                                data: [],
                                borderColor: '#9CA3AF',
                                backgroundColor: 'transparent',
                                borderDash: [5, 5],
                                fill: false,
                                cubicInterpolationMode: 'monotone'
                            }
                        ]
                    },
                    options: document.documentElement.classList.contains('dark')
                        ? { ...extruderChartOptions, scales: { ...extruderChartOptions.scales, ...darkModeOptions.scales } }
                        : extruderChartOptions
                }
            );
        }

        // Update temperature history
        function updateTempHistory(type, current, target) {
            const maxPoints = 30; // Reduce number of points to show
            
            tempHistory[type].current.push(current);
            tempHistory[type].target.push(target);
            tempHistory[type].labels.push('');

            // Keep only the last maxPoints points
            if (tempHistory[type].current.length > maxPoints) {
                tempHistory[type].current.shift();
                tempHistory[type].target.shift();
                tempHistory[type].labels.shift();
            }

            // Update chart max if needed
            const maxTemp = Math.max(
                Math.max(...tempHistory[type].current),
                Math.max(...tempHistory[type].target)
            );
            
            const chart = type === 'bed' ? bedTempChart : (type === 'ext1' ? ext1TempChart : ext2TempChart);
            const suggestedMax = Math.ceil((maxTemp + 10) / 50) * 50; // Round up to nearest 50
            chart.options.scales.y.suggestedMax = Math.max(250, suggestedMax);
            chart.options.scales.y.ticks.stepSize = Math.max(25, Math.floor(suggestedMax / 5));
        }

        // Update temperature charts
        function updateTempCharts() {
            // Update bed temperature chart
            bedTempChart.data.labels = tempHistory.bed.labels;
            bedTempChart.data.datasets[0].data = tempHistory.bed.current;
            bedTempChart.data.datasets[1].data = tempHistory.bed.target;
            bedTempChart.update();

            // Update extruder 1 temperature chart
            ext1TempChart.data.labels = tempHistory.ext1.labels;
            ext1TempChart.data.datasets[0].data = tempHistory.ext1.current;
            ext1TempChart.data.datasets[1].data = tempHistory.ext1.target;
            ext1TempChart.update();

            // Update extruder 2 temperature chart
            ext2TempChart.data.labels = tempHistory.ext2.labels;
            ext2TempChart.data.datasets[0].data = tempHistory.ext2.current;
            ext2TempChart.data.datasets[1].data = tempHistory.ext2.target;
            ext2TempChart.update();
        }

        // Format seconds to HH:MM:SS
        function formatTime(seconds) {
            if (!seconds) return '--:--:--';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }

        // Format date to local time
        function formatDate(dateString) {
            if (!dateString) return '--';
            const date = new Date(dateString);
            return date.toLocaleString();
        }

        // Load current configuration
        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                if (config.printer_ip) {
                    connectPrinter(config.printer_ip);
                }
            } catch (error) {
                console.error('Error loading configuration:', error);
            }
        }

        async function connectPrinter(printerIp) {
            const cameraFeed = document.getElementById('camera-feed');
            const cameraOverlay = document.getElementById('camera-overlay');
            try {
                const response = await fetch('/api/test-connection');
                const data = await response.json();
                if (data.connected && printerIp) {
                    cameraFeed.src = `http://${printerIp}:8080/?action=stream`;
                    cameraOverlay.style.display = 'none';
                    clearInterval(statsInterval);
                    updatePrinterStats();
                    statsInterval = setInterval(updatePrinterStats, 1000);
                } else {
                    cameraFeed.src = '';
                    cameraOverlay.style.display = 'flex';
                    clearInterval(statsInterval);
                }
            } catch {
                cameraFeed.src = '';
                cameraOverlay.style.display = 'flex';
                clearInterval(statsInterval);
            }
        }

        let lastPos = null;
        function updateMotion(x, y, z, status) {
            const threshold = 0.05;
            const dot = document.getElementById('motion-dot');
            const text = document.getElementById('motion-text');

            if (lastPos) {
                const dx = Math.abs(x - lastPos.x);
                const dy = Math.abs(y - lastPos.y);
                const dz = Math.abs(z - lastPos.z);
                const any = dx > threshold || dy > threshold || dz > threshold;

                const mx = Math.min(dx * 20, 100);
                const my = Math.min(dy * 20, 100);
                const mz = Math.min(dz * 20, 100);
                document.getElementById('motion-x-bar').style.width = mx + '%';
                document.getElementById('motion-y-bar').style.width = my + '%';
                document.getElementById('motion-z-bar').style.width = mz + '%';

                if (any) {
                    dot.className = 'motion-dot moving';
                    text.textContent = 'Traveling';
                } else if (status === 'printing') {
                    dot.className = 'motion-dot printing';
                    text.textContent = 'Extruding';
                } else {
                    dot.className = 'motion-dot idle';
                    text.textContent = 'Idle';
                }
            } else if (status === 'printing') {
                dot.className = 'motion-dot printing';
                text.textContent = 'Extruding';
            }
            lastPos = { x, y, z };
        }

        async function updateHealthScore() {
            try {
                const resp = await fetch('/api/health-score');
                if (!resp.ok) return;
                const data = await resp.json();
                const score = data.score;
                document.getElementById('health-score').textContent = score;
                const arc = document.getElementById('health-arc');
                const circ = Math.PI * 2 * 50;
                const offset = circ * (1 - score / 100);
                arc.style.strokeDasharray = `${circ - offset} ${circ}`;
                let color = '#22c55e';
                if (score < 60) color = '#ef4444';
                else if (score < 80) color = '#f59e0b';
                arc.style.stroke = color;
                document.getElementById('health-score').style.color = color;

                const comps = data.components || {};
                document.getElementById('h-temp').textContent = comps.temperature ?? '--';
                document.getElementById('h-status').textContent = comps.status ?? '--';
                document.getElementById('h-progress').textContent = comps.progress ?? '--';
                document.getElementById('h-material').textContent = comps.material ?? '--';
                document.getElementById('h-errors').textContent = comps.errors ?? '--';
                document.getElementById('h-cores').textContent = comps.cores ?? '--';
                document.getElementById('h-cal').textContent = comps.calibration ?? '--';

                const issuesEl = document.getElementById('health-issues');
                if (data.issues && data.issues.length > 0) {
                    issuesEl.textContent = data.issues.join('; ');
                    issuesEl.classList.remove('hidden');
                    const count = data.issues.length;
                    const summary = count === 1 ? data.issues[0] : `${count} issues:\n${data.issues.join('\n')}`;
                    addAlert(score < 60 ? 'error' : 'warning', 'Print Health', summary, 'health-summary', true);
                } else {
                    issuesEl.classList.add('hidden');
                    removeAlertsByType('health-summary');
                }
            } catch (e) {}
        }

        function updatePrinterIndicator() {
            fetch('/api/printer-stats')
                .then(r => r.json())
                .then(d => {
                    const dot = document.getElementById('printer-indicator');
                    const label = document.getElementById('printer-indicator-label');
                    if (!dot) return;
                    const status = (d.status || '').toLowerCase();
                    if (status === 'printing') {
                        dot.style.background = '#3b82f6';
                        dot.style.animation = 'none';
                        if (label) label.textContent = 'Printing';
                    } else if (status === 'idle') {
                        dot.style.background = '#9ca3af';
                        dot.style.animation = 'none';
                        if (label) label.textContent = 'Idle';
                    } else if (status === 'error' || status === 'maintenance') {
                        dot.style.background = '#ef4444';
                        dot.style.animation = 'none';
                        if (label) label.textContent = status;
                    } else {
                        dot.style.background = '#22c55e';
                        dot.style.animation = 'pulse-dot 0.8s ease-in-out infinite';
                        if (label) label.textContent = 'Traveling';
                    }
                })
                .catch(() => {
                    const dot = document.getElementById('printer-indicator');
                    if (dot) { dot.style.background = '#ef4444'; dot.style.animation = 'none'; }
                });
        }

        // Update printer stats
        async function updatePrinterStats() {
            try {
                const response = await fetch('/api/printer-stats');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                console.log('Printer data received:', data); // Debug log

                // Update status
                const statusElement = document.getElementById('printer-status');
                statusElement.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
                statusElement.className = `px-3 py-1 rounded-full text-sm font-medium ${getStatusClass(data.status)}`;

                // Update temperatures with gauges
                if (data.bed && data.bed.temperature) {
                    const currentTemp = data.bed.temperature.current;
                    const targetTemp = data.bed.temperature.target;
                    document.getElementById('bed-temp-val').textContent = currentTemp.toFixed(1);
                    document.getElementById('bed-target-val').textContent = `Target: ${targetTemp}°`;
                    setTempGauge('bed-gauge', 'bed-gauge-arc', currentTemp, 120);
                    updateTempHistory('bed', currentTemp, targetTemp);
                }

                if (data.heads && data.heads[0] && data.heads[0].extruders) {
                    if (data.heads[0].extruders[0] && data.heads[0].extruders[0].hotend) {
                        const currentTemp = data.heads[0].extruders[0].hotend.temperature.current;
                        const targetTemp = data.heads[0].extruders[0].hotend.temperature.target;
                        document.getElementById('ext1-temp-val').textContent = currentTemp.toFixed(1);
                        document.getElementById('ext1-target-val').textContent = `Target: ${targetTemp}°`;
                        setTempGauge('ext1-gauge', 'ext1-gauge-arc', currentTemp, 300);
                        updateTempHistory('ext1', currentTemp, targetTemp);
                    }
                    if (data.heads[0].extruders[1] && data.heads[0].extruders[1].hotend) {
                        const currentTemp = data.heads[0].extruders[1].hotend.temperature.current;
                        const targetTemp = data.heads[0].extruders[1].hotend.temperature.target;
                        document.getElementById('ext2-temp-val').textContent = currentTemp.toFixed(1);
                        document.getElementById('ext2-target-val').textContent = `Target: ${targetTemp}°`;
                        setTempGauge('ext2-gauge', 'ext2-gauge-arc', currentTemp, 300);
                        updateTempHistory('ext2', currentTemp, targetTemp);
                    }
                }

                // Ambient temperature
                try {
                    const ambResp = await fetch('/api/ambient-temperature');
                    if (ambResp.ok) {
                        const amb = await ambResp.json();
                        if (amb.current != null) {
                            document.getElementById('ambient-temp').textContent = amb.current.toFixed(1);
                        }
                    }
                } catch (e) {}

                updateTempCharts();

                if (data.heads && data.heads[0] && data.heads[0].position) {
                    const pos = data.heads[0].position;
                    document.getElementById('pos-x').textContent = pos.x.toFixed(1);
                    document.getElementById('pos-y').textContent = pos.y.toFixed(1);
                    document.getElementById('pos-z').textContent = pos.z.toFixed(1);
                    updateMotion(pos.x, pos.y, pos.z, data.status);
                }

                // Update fan
                if (data.heads && data.heads[0]) {
                    document.getElementById('fan-speed').textContent = data.heads[0].fan;
                }

            } catch (error) {
                console.error('Error updating printer stats:', error);
                // Update status to show error
                const statusElement = document.getElementById('printer-status');
                statusElement.textContent = 'Error';
                statusElement.className = 'px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800';
            }
        }

        function getStatusClass(status) {
            switch (status) {
                case 'printing':
                    return 'bg-green-100 text-green-800';
                case 'idle':
                    return 'bg-blue-100 text-blue-800';
                case 'error':
                    return 'bg-red-100 text-red-800';
                default:
                    return 'bg-gray-100 text-gray-800';
            }
        }

        // Test connection to printer
        // Update print job information
        async function updatePrintJob() {
            try {
                const response = await fetch('/api/print-job');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                const jobDetails = document.getElementById('job-details');
                const noJobMessage = document.getElementById('no-job-message');
                const jobStatus = document.getElementById('job-status');

                if (stateChanging) {
                    const currentState = (data.state || '').toLowerCase();
                    if (currentState !== 'pausing' && currentState !== 'resuming' && currentState !== 'aborting') {
                        stateChanging = false;
                        document.getElementById('state-in-progress').classList.add('hidden');
                        document.getElementById('print-controls').classList.remove('hidden');
                    }
                }

                if (data.state) {
                    jobDetails.classList.remove('hidden');
                    noJobMessage.classList.add('hidden');
                    
                    // Update job status
                    jobStatus.textContent = data.state.charAt(0).toUpperCase() + data.state.slice(1);
                    jobStatus.className = `px-3 py-1 rounded-full text-sm font-medium ${getJobStatusClass(data.state)}`;

                    // Update job name
                    document.getElementById('job-name').textContent = data.name || 'Unnamed Job';

                    // Update progress
                    const progress = Math.round((data.progress || 0) * 100);
                    document.getElementById('progress-text').textContent = `${progress}%`;
                    document.getElementById('progress-bar').style.width = `${progress}%`;

                    // Update times
                    document.getElementById('time-elapsed').textContent = formatTime(data.time_elapsed);
                    document.getElementById('time-total').textContent = formatTime(data.time_total);
                    document.getElementById('time-started').textContent = formatDate(data.datetime_started);

                    const remaining = data.time_total - data.time_elapsed;
                    document.getElementById('time-remaining').textContent = `${formatTime(remaining)} remaining`;

                    const state = (data.state || '').toLowerCase();
                    document.getElementById('btn-pause').classList.toggle('hidden', state !== 'printing');
                    document.getElementById('btn-resume').classList.toggle('hidden', state !== 'paused');
                    document.getElementById('btn-abort').classList.toggle('hidden', !['printing','paused'].includes(state));
                } else {
                    jobDetails.classList.add('hidden');
                    noJobMessage.classList.remove('hidden');
                    jobStatus.textContent = 'No Job';
                    jobStatus.className = 'px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800';
                    
                    // Display the message from the server if available
                    if (data.message) {
                        document.getElementById('no-job-message').textContent = data.message;
                    }
                }

            } catch (error) {
                console.error('Error updating print job:', error);
                
                // Show a user-friendly error message
                const jobDetails = document.getElementById('job-details');
                const noJobMessage = document.getElementById('no-job-message');
                const jobStatus = document.getElementById('job-status');
                
                jobDetails.classList.add('hidden');
                noJobMessage.classList.remove('hidden');
                noJobMessage.textContent = 'Unable to fetch print job information. Please check your connection.';
                stateChanging = false;
                document.getElementById('state-in-progress').classList.add('hidden');
                document.getElementById('print-controls').classList.remove('hidden');
                jobStatus.textContent = 'Error';
                jobStatus.className = 'px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800';
            }
        }

        let stateChanging = false;

        async function controlPrint(action) {
            const btn = document.getElementById('btn-' + action);
            btn.disabled = true;
            const label = action === 'pause' ? 'Pausing' : action === 'resume' ? 'Resuming' : 'Aborting';
            btn.textContent = label + '...';
            stateChanging = true;
            document.getElementById('state-change-text').textContent = label + '...';
            document.getElementById('state-in-progress').classList.remove('hidden');
            document.getElementById('print-controls').classList.add('hidden');
            try {
                const resp = await fetch('/api/print/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ action })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    addAlert('error', 'Print Control', data.error || 'Failed to ' + action, 'print-control');
                    stateChanging = false;
                    document.getElementById('state-in-progress').classList.add('hidden');
                    document.getElementById('print-controls').classList.remove('hidden');
                } else {
                    addAlert('success', 'Print Control', data.message || 'Print job ' + action + 'd', 'print-control');
                }
            } catch (e) {
                addAlert('error', 'Print Control', 'Network error: ' + e.message, 'print-control');
                stateChanging = false;
                document.getElementById('state-in-progress').classList.add('hidden');
                document.getElementById('print-controls').classList.remove('hidden');
            }
            btn.disabled = false;
            btn.textContent = action === 'pause' ? 'Pause' : action === 'resume' ? 'Resume' : 'Abort';
            setTimeout(() => updatePrintJob(), 1500);
        }

        function getJobStatusClass(status) {
            switch (status) {
                case 'printing':
                    return 'bg-green-100 text-green-800';
                case 'paused':
                    return 'bg-yellow-100 text-yellow-800';
                case 'error':
                    return 'bg-red-100 text-red-800';
                case 'finished':
                    return 'bg-blue-100 text-blue-800';
                default:
                    return 'bg-gray-100 text-gray-800';
            }
        }

        // Update print core information
        async function updatePrintCores() {
            try {
                const response = await fetch('/api/print-cores');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                
                // Update Print Core 0
                if (data['0'].last_extrusion) {
                    document.getElementById('core0-last-extrusion').textContent = 
                        `${data['0'].last_extrusion.amount.toFixed(2)} mm in ${data['0'].last_extrusion.time.toFixed(1)} s`;
                    document.getElementById('core0-remaining').textContent = 
                        `${data['0'].remaining_length.toFixed(0)} mm`;
                    document.getElementById('core0-usage-time').textContent = 
                        `Usage: ${formatTime(data['0'].usage_duration)}`;
                }

                // Update Print Core 1
                if (data['1'].last_extrusion) {
                    document.getElementById('core1-last-extrusion').textContent = 
                        `${data['1'].last_extrusion.amount.toFixed(2)} mm in ${data['1'].last_extrusion.time.toFixed(1)} s`;
                    document.getElementById('core1-remaining').textContent = 
                        `${data['1'].remaining_length.toFixed(0)} mm`;
                    document.getElementById('core1-usage-time').textContent = 
                        `Usage: ${formatTime(data['1'].usage_duration)}`;
                }

            } catch (error) {
                console.error('Error updating print cores:', error);
            }
        }

        // Show success message
        // Helper function to determine alert type from message
        function getAlertType(message) {
            const lowerMessage = message.toLowerCase();
            if (lowerMessage.includes('error') || lowerMessage.includes('failed') || lowerMessage.includes('critical')) {
                return 'error';
            } else if (message.includes('WAR') || lowerMessage.includes('attention')) {
                return 'warning';
            } else if (message.includes('INF -') || (lowerMessage.includes('systemservice') && lowerMessage.includes('scheduling next check'))) {
                return 'info';
            }
            return 'info';
        }

        // Dismiss alert
        function dismissAlert(alertId) {
            const alertElement = document.querySelector(`[data-alert-id="${alertId}"]`);
            if (alertElement) {
                alertElement.remove();
                updateAlertCount();
            }
        }

        // Update alerts count badge
        function updateAlertCount() {
            const alertsContainer = document.getElementById('alerts-container');
            const noAlertsMessage = document.getElementById('no-alerts-message');
            const countBadge = document.getElementById('alerts-count');
            
            // Count actual alerts (excluding the "no alerts" message)
            const alerts = alertsContainer.querySelectorAll('.alert-error, .alert-warning, .alert-info');
            const count = alerts.length;
            
            // Update count badge
            if (count === 0) {
                countBadge.textContent = '0';
                countBadge.style.display = 'none';
                noAlertsMessage.style.display = 'block';
            } else {
                countBadge.textContent = count.toString();
                countBadge.style.display = 'block';
                noAlertsMessage.style.display = 'none';
            }
        }

        // Note: log-entry alert processing now happens server-side, and alert
        // rendering is handled by the single addAlert()/addAlertFromServer()
        // definitions further down this file.

        // Add function to remove alerts by type
        function removeAlertsByType(alertType) {
            const alertsContainer = document.getElementById('alerts-container');
            const alerts = alertsContainer.querySelectorAll(`[data-type="${alertType}"]`);
            alerts.forEach(alert => alert.remove());
            updateAlertCount();
        }

        // Update alerts from server data
        function updateAlertsFromServer(alerts) {
            const alertsContainer = document.getElementById('alerts-container');
            const noAlertsMessage = document.getElementById('no-alerts-message');
            const currentAlertIds = new Set(alerts.map(alert => alert.id));
            
            // Remove alerts that are no longer active
            Array.from(alertsContainer.children).forEach(alertElement => {
                const alertId = alertElement.dataset.alertId;
                if (alertId) {
                    // Keep local alerts (starting with 'local-') unless they're system connection alerts
                    const isLocalAlert = alertId.startsWith('local-');
                    const isSystemConnection = alertElement.dataset.type === 'system-connection';
                    
                    if (!isLocalAlert || isSystemConnection) {
                        if (!currentAlertIds.has(alertId)) {
                            alertElement.remove();
                            activeAlerts.delete(alertId);
                        }
                    }
                }
            });
            
            // Add or update alerts
            alerts.forEach(alert => {
                // Skip resolved alerts
                if (alert.resolved_at) {
                    const existingElement = document.querySelector(`[data-alert-id="${alert.id}"]`);
                    if (existingElement) {
                        existingElement.remove();
                        activeAlerts.delete(alert.id);
                    }
                    return;
                }

                const existingElement = document.querySelector(`[data-alert-id="${alert.id}"]`);
                if (!existingElement) {
                    addAlertFromServer(alert);
                } else {
                    // Update existing alert if needed
                    const messageElement = existingElement.querySelector('p');
                    if (messageElement && messageElement.textContent !== alert.details.raw_message) {
                        messageElement.textContent = alert.details.raw_message || '';
                    }
                }
            });
            
            // Update alert count and visibility
            updateAlertCount();
        }

        // Add message pattern tracking
        let messagePatterns = new Map(); // Store message patterns and their variations

        // Add status tracking variables
        let lastLogTimestamp = null;
        let statusCheckInterval;

        // Update the updateSystemLog function
        async function updateSystemLog() {
            try {
                const response = await fetch('/api/system-log');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const logs = await response.json();
                const container = document.getElementById('log-entries');
                let hasNewMessages = false;

                for (const log of logs) {
                    if (!seenMessages.has(log.raw)) {
                        seenMessages.add(log.raw);
                        hasNewMessages = true;

                        const dt = log.datetime ? new Date(log.datetime) : null;
                        const displayTime = dt ? dt.toLocaleString(undefined, {
                            month: 'short', day: 'numeric',
                            hour: '2-digit', minute: '2-digit', second: '2-digit'
                        }) : log.timestamp;

                        // Create log entry
                        const entry = document.createElement('div');
                        entry.className = `log-entry type-${log.type}`;
                        
                        // Format the log message (escape first - log messages come from the
                        // printer and must not be trusted as HTML)
                        const formattedMessage = escapeHtml(log.message)
                            .replace(/\[(\d+)\]/g, '<span class="text-gray-500">[$1]</span>')
                            .replace(/(WAR|INF|ERR)(\s*-\s*)/g, '<span class="text-gray-500">$1</span>$2');

                        entry.innerHTML = `
                            <span class="log-timestamp">${escapeHtml(displayTime)}</span>
                            ${log.occurrences > 1 ? `<span class="log-count">(${log.occurrences}×)</span>` : ''}
                            <span class="log-message">${formattedMessage}</span>
                        `;
                        
                        container.insertBefore(entry, container.firstChild);
                    }
                }

                // Keep only the last 100 messages in the DOM
                while (container.children.length > 100) {
                    container.removeChild(container.lastChild);
                }

                // Update status and badge
                const status = document.getElementById('log-status-popup');
                if (hasNewMessages) {
                    status.textContent = 'Active';
                    status.className = 'px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 rounded-full';
                    updateLogsBadge();
                    setTimeout(() => {
                        status.textContent = 'Idle';
                        status.className = 'px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 rounded-full';
                    }, 1000);
                }

            } catch (error) {
                console.error('Error updating system log:', error);
                const status = document.getElementById('log-status-popup');
                status.textContent = 'Error';
                status.className = 'px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 rounded-full';
            }
        }

        function updateLogsBadge() {
            const count = document.getElementById('log-entries').children.length;
            const badge = document.getElementById('logs-badge');
            if (count > 0) {
                badge.textContent = count;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }

        function toggleLogs() {
            const popup = document.getElementById('logs-popup');
            popup.classList.toggle('open');
        }

        function clearLogs() {
            document.getElementById('log-entries').innerHTML = '';
            seenMessages = new Set();
            const badge = document.getElementById('logs-badge');
            badge.classList.add('hidden');
        }

        // Function to update log status display
        function updateLogStatus(status) {
            const statusElement = document.getElementById('log-status-popup');
            switch (status) {
                case 'active':
                    statusElement.textContent = 'Active';
                    statusElement.className = 'ml-4 px-3 py-1 text-sm font-medium bg-green-100 text-green-800 rounded-full';
                    break;
                case 'idle':
                    statusElement.textContent = 'Idle';
                    statusElement.className = 'ml-4 px-3 py-1 text-sm font-medium bg-gray-100 text-gray-800 rounded-full';
                    break;
                case 'error':
                    statusElement.textContent = 'Error';
                    statusElement.className = 'ml-4 px-3 py-1 text-sm font-medium bg-red-100 text-red-800 rounded-full';
                    break;
            }
        }

        // Function to check log activity
        function checkLogActivity() {
            if (lastLogTimestamp) {
                const currentTime = new Date();
                const timeSinceLastLog = currentTime - lastLogTimestamp;
                // If no new logs in 5 seconds, mark as idle
                if (timeSinceLastLog > 5000) {
                    updateLogStatus('idle');
                    clearInterval(statusCheckInterval);
                    statusCheckInterval = null;
                }
            }
        }

        // Initialize flow charts
        function initFlowCharts() {
            const flowChartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false,
                            drawBorder: false
                        }
                    },
                    y: {
                        display: true,
                        position: 'right',
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)',
                            drawBorder: false,
                            borderDash: [5, 5]
                        },
                        ticks: {
                            font: {
                                size: 10
                            },
                            padding: 5
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: false
                    }
                },
                elements: {
                    point: {
                        radius: 0,
                        hoverRadius: 0
                    },
                    line: {
                        tension: 0.4,
                        borderWidth: 1.5
                    }
                }
            };

            // Dark mode chart options
            const darkFlowChartOptions = {
                ...flowChartOptions,
                scales: {
                    ...flowChartOptions.scales,
                    y: {
                        ...flowChartOptions.scales.y,
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)',
                            drawBorder: false,
                            borderDash: [5, 5]
                        },
                        ticks: {
                            ...flowChartOptions.scales.y.ticks,
                            color: 'rgba(255, 255, 255, 0.7)'
                        }
                    }
                }
            };

            // Flow rate charts
            window.ext0FlowChart = new Chart(
                document.getElementById('ext0-flow-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: '#3B82F6',
                            backgroundColor: 'transparent',
                            fill: false,
                            cubicInterpolationMode: 'monotone'
                        }]
                    },
                    options: document.documentElement.classList.contains('dark') ? darkFlowChartOptions : flowChartOptions
                }
            );

            window.ext1FlowChart = new Chart(
                document.getElementById('ext1-flow-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: '#3B82F6',
                            backgroundColor: 'transparent',
                            fill: false,
                            cubicInterpolationMode: 'monotone'
                        }]
                    },
                    options: document.documentElement.classList.contains('dark') ? darkFlowChartOptions : flowChartOptions
                }
            );

            // Power charts
            window.ext0PowerChart = new Chart(
                document.getElementById('ext0-power-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: '#EF4444',
                            backgroundColor: 'transparent',
                            fill: false,
                            cubicInterpolationMode: 'monotone'
                        }]
                    },
                    options: document.documentElement.classList.contains('dark') ? darkFlowChartOptions : flowChartOptions
                }
            );

            window.ext1PowerChart = new Chart(
                document.getElementById('ext1-power-chart'),
                {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: '#EF4444',
                            backgroundColor: 'transparent',
                            fill: false,
                            cubicInterpolationMode: 'monotone'
                        }]
                    },
                    options: document.documentElement.classList.contains('dark') ? darkFlowChartOptions : flowChartOptions
                }
            );
        }

        // Update flow history
        function updateFlowHistory(extruder, flow, power) {
            flowHistory[extruder].flow.push(flow);
            flowHistory[extruder].power.push(power);
            flowHistory[extruder].labels.push('');

            // Keep only the last MAX_TEMP_HISTORY points
            if (flowHistory[extruder].flow.length > MAX_TEMP_HISTORY) {
                flowHistory[extruder].flow.shift();
                flowHistory[extruder].power.shift();
                flowHistory[extruder].labels.shift();
            }
        }

        // Update flow charts
        function updateFlowCharts() {
            // Update extruder 0 charts
            ext0FlowChart.data.labels = flowHistory.ext0.labels;
            ext0FlowChart.data.datasets[0].data = flowHistory.ext0.flow;
            ext0FlowChart.update();

            ext0PowerChart.data.labels = flowHistory.ext0.labels;
            ext0PowerChart.data.datasets[0].data = flowHistory.ext0.power;
            ext0PowerChart.update();

            // Update extruder 1 charts
            ext1FlowChart.data.labels = flowHistory.ext1.labels;
            ext1FlowChart.data.datasets[0].data = flowHistory.ext1.flow;
            ext1FlowChart.update();

            ext1PowerChart.data.labels = flowHistory.ext1.labels;
            ext1PowerChart.data.datasets[0].data = flowHistory.ext1.power;
            ext1PowerChart.update();
        }

        // Update flow data with charts
        async function updateFlowData() {
            try {
                const sampleSize = document.getElementById('sample-size').value;
                const response = await fetch(`/api/flow-data/${sampleSize}`);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                
                // Update Extruder 0
                const ext0Flow = data.extruder0.flow_rate;
                const ext0Power = data.extruder0.heater_power;
                document.getElementById('ext0-flow').textContent = `${ext0Flow.toFixed(1)} units/s`;
                document.getElementById('ext0-power').textContent = `${((ext0Power / MAX_HEATER_POWER) * 100).toFixed(1)}%`;
                document.getElementById('ext0-steps').textContent = data.extruder0.total_steps.toLocaleString();
                document.getElementById('ext0-flow-bar').style.width = `${(ext0Flow / MAX_FLOW_RATE) * 100}%`;
                document.getElementById('ext0-power-bar').style.width = `${(ext0Power / MAX_HEATER_POWER) * 100}%`;
                updateFlowHistory('ext0', ext0Flow, (ext0Power / MAX_HEATER_POWER) * 100);
                
                // Update Extruder 1
                const ext1Flow = data.extruder1.flow_rate;
                const ext1Power = data.extruder1.heater_power;
                document.getElementById('ext1-flow').textContent = `${ext1Flow.toFixed(1)} units/s`;
                document.getElementById('ext1-power').textContent = `${((ext1Power / MAX_HEATER_POWER) * 100).toFixed(1)}%`;
                document.getElementById('ext1-steps').textContent = data.extruder1.total_steps.toLocaleString();
                document.getElementById('ext1-flow-bar').style.width = `${(ext1Flow / MAX_FLOW_RATE) * 100}%`;
                document.getElementById('ext1-power-bar').style.width = `${(ext1Power / MAX_HEATER_POWER) * 100}%`;
                updateFlowHistory('ext1', ext1Flow, (ext1Power / MAX_HEATER_POWER) * 100);

                // Update active states
                const activeExtruder = data.active_extruder;
                document.getElementById('ext0-active').className = `px-2 py-1 text-xs rounded-full ${activeExtruder === 0 ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`;
                document.getElementById('ext0-active').textContent = activeExtruder === 0 ? 'Active' : 'Inactive';
                document.getElementById('ext1-active').className = `px-2 py-1 text-xs rounded-full ${activeExtruder === 1 ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`;
                document.getElementById('ext1-active').textContent = activeExtruder === 1 ? 'Active' : 'Inactive';

                // Update flow charts
                updateFlowCharts();

            } catch (error) {
                console.error('Error updating flow data:', error);
            }
        }

        let materialInterval;
        // For 2.85mm filament:
        // Cross-sectional area = π * (2.85/2)^2 = 6.379 mm²
        // For PLA (density ~1.24 g/cm³):
        // 1 meter = 6.379 mm² * 1000 mm * 1.24 g/cm³ * (1/1000) cm³/mm³ = ~7.91g
        // So 1kg = ~126.4 meters = 126,400mm
        const MM_PER_KG = 126400; // mm of 2.85mm filament per kg

        // Update material remaining data
        async function updateMaterialRemaining() {
            try {
                const response = await fetch('/api/material-remaining');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                const spoolSize = parseFloat(document.getElementById('spool-size').value) || 1.0;
                
                // Update Extruder 0
                const ext0Data = data.extruder0;
                if (ext0Data.error) {
                    document.getElementById('ext0-material-status').textContent = 'Error';
                    document.getElementById('ext0-material-status').className = 'px-2 py-1 text-xs rounded-full bg-red-100 text-red-800';
                    document.getElementById('ext0-material-length').textContent = '-- mm';
                    document.getElementById('ext0-material-pct').textContent = '--';
                    setMatGauge('ext0-mat-arc', 0);
                    document.getElementById('ext0-material-updated').textContent = `Last updated: ${ext0Data.timestamp}`;
                    document.getElementById('ext0-material-weight').textContent = '-- kg';
                    addAlert('error', 'Extruder 0', 'Failed to fetch material data', 'material-0');
                } else {
                    const length = ext0Data.length_remaining;
                    const weight = (length / MM_PER_KG).toFixed(3);
                    const percentage = (length / (spoolSize * MM_PER_KG)) * 100;
                    
                    const isDark = document.documentElement.classList.contains('dark');
                    document.getElementById('ext0-material-status').textContent = length > 0 ? 'Loaded' : 'Empty';
                    document.getElementById('ext0-material-status').className = `px-2 py-1 text-xs rounded-full ${length > 0 ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`;
                    document.getElementById('ext0-material-length').textContent = `${length.toFixed(1)} mm`;
                    document.getElementById('ext0-material-pct').textContent = percentage.toFixed(0);
                    setMatGauge('ext0-mat-arc', percentage / 100);
                    document.getElementById('ext0-material-updated').textContent = `Last updated: ${ext0Data.timestamp}`;
                    document.getElementById('ext0-material-weight').textContent = `${weight} kg`;

                    // Handle material level warnings for Extruder 0
                    if (length > 0) {
                        const existingWarning = Array.from(document.querySelectorAll('.alert-entry'))
                            .find(alert => alert.getAttribute('data-type') === 'material-0');
                        
                        if (percentage <= 5) {
                            if (existingWarning) {
                                // Update existing warning to critical
                                existingWarning.className = 'alert-entry alert-error';
                                existingWarning.querySelector('h4').textContent = 'Extruder 0';
                                existingWarning.querySelector('p').textContent = `Critical: Material level is very low (${percentage.toFixed(1)}% remaining)`;
                            } else {
                                addAlert('error', 'Extruder 0', `Critical: Material level is very low (${percentage.toFixed(1)}% remaining)`, 'material-0');
                            }
                        } else if (percentage <= 20) {
                            if (existingWarning) {
                                // Update existing warning
                                existingWarning.className = 'alert-entry alert-warning';
                                existingWarning.querySelector('h4').textContent = 'Extruder 0';
                                existingWarning.querySelector('p').textContent = `Warning: Material level is low (${percentage.toFixed(1)}% remaining)`;
                            } else {
                                addAlert('warning', 'Extruder 0', `Warning: Material level is low (${percentage.toFixed(1)}% remaining)`, 'material-0');
                            }
                        } else {
                            removeAlertsByType('material-0');
                        }
                    }
                }
                
                // Update Extruder 1
                const ext1Data = data.extruder1;
                if (ext1Data.error) {
                    document.getElementById('ext1-material-status').textContent = 'Error';
                    document.getElementById('ext1-material-status').className = 'px-2 py-1 text-xs rounded-full bg-red-100 text-red-800';
                    document.getElementById('ext1-material-length').textContent = '-- mm';
                    document.getElementById('ext1-material-pct').textContent = '--';
                    setMatGauge('ext1-mat-arc', 0);
                    document.getElementById('ext1-material-updated').textContent = `Last updated: ${ext1Data.timestamp}`;
                    document.getElementById('ext1-material-weight').textContent = '-- kg';
                    addAlert('error', 'Extruder 1', 'Failed to fetch material data', 'material-1');
                } else {
                    const length = ext1Data.length_remaining;
                    const weight = (length / MM_PER_KG).toFixed(3);
                    const percentage = (length / (spoolSize * MM_PER_KG)) * 100;
                    
                    document.getElementById('ext1-material-status').textContent = length > 0 ? 'Loaded' : 'Empty';
                    document.getElementById('ext1-material-status').className = `px-2 py-1 text-xs rounded-full ${length > 0 ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`;
                    document.getElementById('ext1-material-length').textContent = `${length.toFixed(1)} mm`;
                    document.getElementById('ext1-material-pct').textContent = percentage.toFixed(0);
                    setMatGauge('ext1-mat-arc', percentage / 100);
                    document.getElementById('ext1-material-updated').textContent = `Last updated: ${ext1Data.timestamp}`;
                    document.getElementById('ext1-material-weight').textContent = `${weight} kg`;

                    // Handle material level warnings for Extruder 1
                    if (length > 0) {
                        const existingWarning = Array.from(document.querySelectorAll('.alert-entry'))
                            .find(alert => alert.getAttribute('data-type') === 'material-1');
                        
                        if (percentage <= 5) {
                            if (existingWarning) {
                                // Update existing warning to critical
                                existingWarning.className = 'alert-entry alert-error';
                                existingWarning.querySelector('h4').textContent = 'Extruder 1';
                                existingWarning.querySelector('p').textContent = `Critical: Material level is very low (${percentage.toFixed(1)}% remaining)`;
                            } else {
                                addAlert('error', 'Extruder 1', `Critical: Material level is very low (${percentage.toFixed(1)}% remaining)`, 'material-1');
                            }
                        } else if (percentage <= 20) {
                            if (existingWarning) {
                                // Update existing warning
                                existingWarning.className = 'alert-entry alert-warning';
                                existingWarning.querySelector('h4').textContent = 'Extruder 1';
                                existingWarning.querySelector('p').textContent = `Warning: Material level is low (${percentage.toFixed(1)}% remaining)`;
                            } else {
                                addAlert('warning', 'Extruder 1', `Warning: Material level is low (${percentage.toFixed(1)}% remaining)`, 'material-1');
                            }
                        } else {
                            removeAlertsByType('material-1');
                        }
                    }
                }

            } catch (error) {
                console.error('Error updating material data:', error);
            }
        }

        // Add spool size change handler
        document.getElementById('spool-size').addEventListener('change', updateMaterialRemaining);

        document.addEventListener('DOMContentLoaded', () => {
            // Start all update intervals
            loadConfig();
            console.log('Starting updates...');
            updatePrinterStats();
            updatePrintJob();
            updatePrintCores();
            updateSystemLog();
            updateProbingReport();  // Initial update
            statsInterval = setInterval(updatePrinterStats, 1000);
            jobInterval = setInterval(updatePrintJob, 1000);
            printCoresInterval = setInterval(updatePrintCores, 1000);
            logInterval = setInterval(updateSystemLog, 1000);
            updateFlowData();
            flowInterval = setInterval(updateFlowData, 1000);
            updateMaterialRemaining();
            materialInterval = setInterval(updateMaterialRemaining, 1000);
            updateHealthScore();
            healthInterval = setInterval(updateHealthScore, 3000);
            updatePrinterIndicator();
            printerIndicatorInterval = setInterval(updatePrinterIndicator, 2000);
        });

        // Cleanup intervals when page is unloaded
        window.addEventListener('beforeunload', () => {
            clearInterval(statsInterval);
            clearInterval(jobInterval);
            clearInterval(printCoresInterval);
            clearInterval(logInterval);
            clearInterval(flowInterval);
            clearInterval(materialInterval);
            clearInterval(healthInterval);
            clearInterval(printerIndicatorInterval);
        });

        let calibrationInterval;

        // Get calibration status class
        function getCalibrationStatusClass(state) {
            switch (state) {
                case 'valid':
                    return 'bg-green-100 text-green-800';
                case 'invalid':
                    return 'bg-red-100 text-red-800';
                default:
                    return 'bg-gray-100 text-gray-800';
            }
        }

        // Update toolhead calibration data
        async function updateToolheadCalibration() {
            try {
                const response = await fetch('/api/toolhead-calibration');
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                
                // Update Extruder 0
                const ext0Data = data.extruder0;
                if (ext0Data.error) {
                    document.getElementById('ext0-cal-status').textContent = 'Error';
                    document.getElementById('ext0-cal-status').className = 'px-2 py-1 text-xs rounded-full bg-red-100 text-red-800';
                    document.getElementById('ext0-x-offset').textContent = '-- mm';
                    document.getElementById('ext0-y-offset').textContent = '-- mm';
                    document.getElementById('ext0-z-offset').textContent = '-- mm';
                    // Add error alert
                    addAlert('error', 'Extruder 0', 'Failed to fetch calibration data', 'calibration-0');
                } else {
                    const status = ext0Data.state || 'unknown';
                    document.getElementById('ext0-cal-status').textContent = status.charAt(0).toUpperCase() + status.slice(1);
                    document.getElementById('ext0-cal-status').className = `px-2 py-1 text-xs rounded-full ${getCalibrationStatusClass(status)}`;
                    document.getElementById('ext0-x-offset').textContent = `${ext0Data.x || 0} mm`;
                    document.getElementById('ext0-y-offset').textContent = `${ext0Data.y || 0} mm`;
                    document.getElementById('ext0-z-offset').textContent = `${ext0Data.z || 0} mm`;
                    
                    // Handle calibration status
                    if (status === 'invalid') {
                        addAlert('error', 'Extruder 0', 'Calibration table is invalid - recalibration required', 'calibration-0', false);
                    } else {
                        removeAlertsByType('calibration-0');
                    }
                }
                
                // Update Extruder 1
                const ext1Data = data.extruder1;
                if (ext1Data.error) {
                    document.getElementById('ext1-cal-status').textContent = 'Error';
                    document.getElementById('ext1-cal-status').className = 'px-2 py-1 text-xs rounded-full bg-red-100 text-red-800';
                    document.getElementById('ext1-x-offset').textContent = '-- mm';
                    document.getElementById('ext1-y-offset').textContent = '-- mm';
                    document.getElementById('ext1-z-offset').textContent = '-- mm';
                    // Add error alert
                    addAlert('error', 'Extruder 1', 'Failed to fetch calibration data', 'calibration-1');
                } else {
                    const status = ext1Data.state || 'unknown';
                    document.getElementById('ext1-cal-status').textContent = status.charAt(0).toUpperCase() + status.slice(1);
                    document.getElementById('ext1-cal-status').className = `px-2 py-1 text-xs rounded-full ${getCalibrationStatusClass(status)}`;
                    document.getElementById('ext1-x-offset').textContent = `${ext1Data.x || 0} mm`;
                    document.getElementById('ext1-y-offset').textContent = `${ext1Data.y || 0} mm`;
                    document.getElementById('ext1-z-offset').textContent = `${ext1Data.z || 0} mm`;
                    
                    // Handle calibration status
                    if (status === 'invalid') {
                        addAlert('error', 'Extruder 1', 'Calibration table is invalid - recalibration required', 'calibration-1', false);
                    } else {
                        removeAlertsByType('calibration-1');
                    }
                }

            } catch (error) {
                console.error('Error updating toolhead calibration:', error);
            }
        }

        // Add calibration interval to initialization
        document.addEventListener('DOMContentLoaded', () => {
            // ... existing initialization code ...
            
            updateToolheadCalibration();
            calibrationInterval = setInterval(updateToolheadCalibration, 1000);
        });

        // Add calibration interval to cleanup
        window.addEventListener('beforeunload', () => {
            // ... existing cleanup code ...
            clearInterval(calibrationInterval);
        });

        // Update probing report data
        async function updateProbingReport() {
            try {
                const response = await fetch('/api/probing-report');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                console.log('Received probe data:', data);  // Debug log
                
                // Update timestamp
                const timestamp = new Date(data.timestamp).toLocaleString();
                document.getElementById('probing-timestamp').textContent = `Last updated: ${timestamp}`;
                
                // Update status
                const statusElement = document.getElementById('probing-status');
                if (data.out_of_tolerance) {
                    statusElement.textContent = 'Out of Tolerance';
                    statusElement.className = 'px-3 py-1 text-sm rounded-full bg-red-100 text-red-800';
                    addAlert('error', 'Bed Leveling', 'Bed leveling is out of tolerance', 'bed-leveling', false);
                } else {
                    statusElement.textContent = 'Within Tolerance';
                    statusElement.className = 'px-3 py-1 text-sm rounded-full bg-green-100 text-green-800';
                    removeAlertsByType('bed-leveling');
                }
                
                // Update statistics
                if (data.statistics) {
                    console.log('Updating statistics:', data.statistics);  // Debug log
                    document.getElementById('min-deviation').textContent = `${data.statistics.min_height.toFixed(3)} mm`;
                    document.getElementById('max-deviation').textContent = `${data.statistics.max_height.toFixed(3)} mm`;
                }
                
                // Update analysis text
                if (data.analysis) {
                    console.log('Updating analysis:', data.analysis);  // Debug log
                    const analysisHtml = `
                        <div class="space-y-2">
                            <p><strong>Status:</strong> <span class="${getAssessmentClass(data.analysis.assessment)}">${data.analysis.assessment}</span></p>
                            <p><strong>Message:</strong> ${data.analysis.message}</p>
                            <p><strong>Point Count:</strong> ${data.statistics.point_count}</p>
                            <p><strong>Max Deviation:</strong> ${data.statistics.max_deviation.toFixed(3)} mm</p>
                            <div class="mt-2">
                                <strong>Recommendations:</strong>
                                <ul class="list-disc pl-4 mt-1">
                                    ${data.analysis.recommendations.map(rec => `<li>${rec}</li>`).join('')}
                                </ul>
                            </div>
                        </div>
                    `;
                    document.getElementById('analysis-text').innerHTML = analysisHtml;
                } else {
                    document.getElementById('analysis-text').textContent = 'Analysis data not available';
                }
                
                // Update bed visualization
                if (data.measurements && data.measurements.length > 0) {
                    console.log('Updating visualization with measurements:', data.measurements);  // Debug log
                    
                    // Get grid dimensions from measurements
                    const uniqueX = [...new Set(data.measurements.map(p => p.x))].sort((a, b) => a - b);
                    const uniqueY = [...new Set(data.measurements.map(p => p.y))].sort((a, b) => b - a);  // Descending for Y
                    const gridCols = uniqueX.length;
                    const gridRows = uniqueY.length;
                    
                    // Update grid layout
                    const visualization = document.getElementById('bed-visualization');
                    visualization.style.gridTemplateColumns = `repeat(${gridCols}, 1fr)`;
                    visualization.innerHTML = ''; // Clear existing points
                    
                    // Create grid points
                    for (let y of uniqueY) {
                        for (let x of uniqueX) {
                            const point = data.measurements.find(p => p.x === x && p.y === y);
                            const pointElement = document.createElement('div');
                            pointElement.className = 'aspect-square rounded-lg flex flex-col items-center justify-center p-2 text-white text-center';
                            
                            if (point) {
                                const deviation = point.deviation;
                                const tolerance = data.tolerance_threshold;
                                
                        let backgroundColor;
                        const absDev = Math.abs(deviation);
                        if (absDev <= tolerance / 2) {
                            backgroundColor = 'bg-green-500';
                        } else if (absDev <= tolerance) {
                            backgroundColor = 'bg-yellow-500';
                        } else {
                            backgroundColor = 'bg-red-500';
                        }
                                
                                pointElement.className += ` ${backgroundColor}`;
                                pointElement.innerHTML = `
                                    <div class="text-xs font-medium">${deviation.toFixed(3)}</div>
                                    <div class="text-xs opacity-75">${x.toFixed(0)},${y.toFixed(0)}</div>
                                `;
                            } else {
                                // Empty grid point
                                pointElement.className += ' bg-gray-200';
                                pointElement.innerHTML = `
                                    <div class="text-xs text-gray-500">No Data</div>
                                    <div class="text-xs opacity-75">${x.toFixed(0)},${y.toFixed(0)}</div>
                                `;
                            }
                            
                            visualization.appendChild(pointElement);
                        }
                    }
                } else {
                    console.log('No measurement data available');  // Debug log
                    const visualization = document.getElementById('bed-visualization');
                    visualization.innerHTML = '<div class="col-span-5 text-center text-gray-500 py-8">No measurement data available</div>';
                }

                // Update 3D visualization
                if (data.measurements && data.measurements.length > 0) {
                    updateBedLevel3D(data.measurements, data.tolerance_threshold || 1.0);
                }
                
            } catch (error) {
                console.error('Error updating probing report:', error);
                // Update status to show error
                const statusElement = document.getElementById('probing-status');
                statusElement.textContent = 'Error';
                statusElement.className = 'px-3 py-1 text-sm rounded-full bg-red-100 text-red-800';
                
                // Clear visualization
                const visualization = document.getElementById('bed-visualization');
                visualization.innerHTML = '<div class="col-span-5 text-center text-red-500 py-8">Error loading bed leveling data</div>';
                
                // Show error in statistics
                document.getElementById('min-deviation').textContent = '-.--- mm';
                document.getElementById('max-deviation').textContent = '-.--- mm';
                document.getElementById('avg-deviation').textContent = '-.--- mm';
                document.getElementById('analysis-text').textContent = 'Error fetching bed leveling data';
                
                addAlert('error', 'Bed Leveling', 'Failed to fetch bed leveling data', 'bed-leveling');
            }
        }

        function getAssessmentClass(assessment) {
            switch (assessment) {
                case 'well-leveled':
                    return 'text-green-600 font-medium';
                case 'acceptable':
                    return 'text-yellow-600 font-medium';
                case 'needs attention':
                    return 'text-red-600 font-medium';
                default:
                    return 'text-gray-600';
            }
        }

        function getRecommendationClass(assessment) {
            switch (assessment) {
                case 'well-leveled':
                    return 'text-green-600';
                case 'acceptable':
                    return 'text-yellow-600';
                case 'needs attention':
                    return 'text-red-600';
                default:
                    return 'text-gray-600';
            }
        }

        function addAlert(type, title, message, alertType = 'general', isDismissible = true) {
            const existing = document.querySelector(`[data-type="${alertType}"]`);
            if (existing) {
                const msgEl = existing.querySelector('p');
                if (msgEl) msgEl.textContent = message;
                existing.querySelector('h4').textContent = title;
                existing.className = existing.className.replace(/alert-\w+/, `alert-${type}`);
                return;
            }

            const container = document.getElementById('alerts-container');
            const noAlertsMsg = document.getElementById('no-alerts-message');
            const id = `local-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

            const el = document.createElement('div');
            el.className = `alert-${type} mb-2 p-4 rounded-lg relative`;
            el.setAttribute('data-alert-id', id);
            el.setAttribute('data-type', alertType);
            el.innerHTML = `
                <div class="flex justify-between items-start">
                    <div>
                        <h4 class="font-semibold">${escapeHtml(title)}</h4>
                        <p class="text-sm">${escapeHtml(message)}</p>
                    </div>
                    ${isDismissible ? `<button onclick="dismissAlert('${id}')" class="text-lg hover:text-gray-800">&times;</button>` : ''}
                </div>
            `;
            container.insertBefore(el, noAlertsMsg);
            updateAlertCount();
        }

        function clearAllAlerts() {
            const container = document.getElementById('alerts-container');
            const alerts = container.querySelectorAll('[data-alert-id]');
            alerts.forEach(a => a.remove());
            activeAlerts.clear();
            updateAlertCount();
        }

        // Add function to remove alerts by type
        function removeAlertsByType(alertType) {
            const alertsContainer = document.getElementById('alerts-container');
            const alerts = alertsContainer.querySelectorAll(`[data-type="${alertType}"]`);
            alerts.forEach(alert => alert.remove());
            updateAlertCount();
        }

        // Update alert styles
        const styleSheet = document.createElement('style');
        styleSheet.textContent = `
            .alert-error {
                background-color: #FEE2E2;
                border: 1px solid #FCA5A5;
                color: #991B1B;
            }
            .alert-warning {
                background-color: #FEF3C7;
                border: 1px solid #FCD34D;
                color: #92400E;
            }
            .alert-info {
                background-color: #EFF6FF;
                border: 1px solid #BFDBFE;
                color: #1E40AF;
            }
            .dark .alert-info {
                background-color: #1e3a8a;
                border-color: #1e40af;
                color: #bfdbfe;
            }
        `;
        document.head.appendChild(styleSheet);

        // Update probing report data with loading state
        async function handleProbingRefresh() {
            const button = document.getElementById('refresh-probing');
            const spinner = document.getElementById('refresh-spinner');
            const buttonText = button.querySelector('span');
            
            // Disable button and show spinner
            button.disabled = true;
            button.classList.add('opacity-75', 'cursor-not-allowed');
            spinner.classList.remove('hidden');
            buttonText.textContent = 'Refreshing...';
            
            try {
                await updateProbingReport();
            } catch (error) {
                console.error('Error during refresh:', error);
            } finally {
                // Re-enable button and hide spinner
                button.disabled = false;
                button.classList.remove('opacity-75', 'cursor-not-allowed');
                spinner.classList.add('hidden');
                buttonText.textContent = 'Refresh';
            }
        }

        // Theme handling
        function setTheme(theme) {
            if (theme === 'dark') {
                document.documentElement.classList.add('dark');
                localStorage.setItem('theme', 'dark');
                // Update chart themes
                const darkOptions = {
                    scales: {
                        y: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.1)'
                            },
                            ticks: {
                                color: 'rgba(255, 255, 255, 0.7)'
                            }
                        }
                    }
                };
                if (window.bedTempChart) {
                    window.bedTempChart.options.scales = darkOptions.scales;
                    window.bedTempChart.update();
                }
                if (window.ext1TempChart) {
                    window.ext1TempChart.options.scales = darkOptions.scales;
                    window.ext1TempChart.update();
                }
                if (window.ext2TempChart) {
                    window.ext2TempChart.options.scales = darkOptions.scales;
                    window.ext2TempChart.update();
                }
            } else {
                document.documentElement.classList.remove('dark');
                localStorage.setItem('theme', 'light');
                // Update chart themes
                const lightOptions = {
                    scales: {
                        y: {
                            grid: {
                                color: 'rgba(0, 0, 0, 0.05)'
                            },
                            ticks: {
                                color: 'rgba(0, 0, 0, 0.7)'
                            }
                        }
                    }
                };
                if (window.bedTempChart) {
                    window.bedTempChart.options.scales = lightOptions.scales;
                    window.bedTempChart.update();
                }
                if (window.ext1TempChart) {
                    window.ext1TempChart.options.scales = lightOptions.scales;
                    window.ext1TempChart.update();
                }
                if (window.ext2TempChart) {
                    window.ext2TempChart.options.scales = lightOptions.scales;
                    window.ext2TempChart.update();
                }
            }
            updateThemeToggle();
        }

        function updateThemeToggle() {
            const isDark = document.documentElement.classList.contains('dark');
            const sunIcon = document.querySelector('.sun-icon');
            const moonIcon = document.querySelector('.moon-icon');
            
            if (isDark) {
                sunIcon.classList.add('hidden');
                moonIcon.classList.remove('hidden');
            } else {
                sunIcon.classList.remove('hidden');
                moonIcon.classList.add('hidden');
            }
        }

        // Initialize theme and charts
        document.addEventListener('DOMContentLoaded', () => {
            const savedTheme = localStorage.getItem('theme') || 'light';
            setTheme(savedTheme);

            // Initialize gauges and charts
            initTempGauges();
            initMatGauges();
            initTempCharts();
            initFlowCharts();

            // Add theme toggle handler
            document.getElementById('theme-toggle').addEventListener('click', () => {
                const isDark = document.documentElement.classList.contains('dark');
                setTheme(isDark ? 'light' : 'dark');
            });

            // ... existing DOMContentLoaded code ...
        });

        // Layout toggle functionality
        document.addEventListener('DOMContentLoaded', function() {
            const layoutToggle = document.getElementById('layout-toggle');
            const verticalIcon = layoutToggle.querySelector('.vertical-icon');
            const desktopIcon = layoutToggle.querySelector('.desktop-icon');
            const singleIcon = layoutToggle.querySelector('.single-icon');
            
            const savedLayout = localStorage.getItem('layout') || 'vertical';
            setLayout(savedLayout);
            
            layoutToggle.addEventListener('click', function() {
                const order = ['vertical', 'desktop', 'single'];
                const current = document.documentElement.classList.contains('single-layout') ? 'single'
                    : document.documentElement.classList.contains('desktop-layout') ? 'desktop'
                    : 'vertical';
                const idx = order.indexOf(current);
                const next = order[(idx + 1) % order.length];
                setLayout(next);
            });
            
            function setLayout(layout) {
                document.documentElement.classList.remove('desktop-layout', 'single-layout');
                verticalIcon.classList.add('hidden');
                desktopIcon.classList.add('hidden');
                singleIcon.classList.add('hidden');
                
                if (layout === 'desktop') {
                    document.documentElement.classList.add('desktop-layout');
                    desktopIcon.classList.remove('hidden');
                } else if (layout === 'single') {
                    document.documentElement.classList.add('single-layout');
                    singleIcon.classList.remove('hidden');
                } else {
                    verticalIcon.classList.remove('hidden');
                }
                
                localStorage.setItem('layout', layout);
            }
        });

        // Handle tolerance threshold changes
        async function loadToleranceThreshold() {
            try {
                const response = await fetch('/api/tolerance-threshold');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                const toleranceSlider = document.getElementById('tolerance-slider');
                const toleranceValue = document.getElementById('tolerance-value');
                
                toleranceSlider.value = data.tolerance_threshold;
                toleranceValue.textContent = `${data.tolerance_threshold} mm`;
            } catch (error) {
                console.error('Error loading tolerance threshold:', error);
            }
        }

        async function saveToleranceThreshold() {
            try {
                const toleranceSlider = document.getElementById('tolerance-slider');
                const toleranceValue = document.getElementById('tolerance-value');
                const newTolerance = parseFloat(toleranceSlider.value);
                
                const response = await fetch('/api/tolerance-threshold', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ tolerance_threshold: newTolerance }),
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                toleranceValue.textContent = `${data.tolerance_threshold} mm`;
                
                // Refresh the probing report to apply the new tolerance
                await updateProbingReport();
                
                // Show success message
                addAlert('success', 'Settings', 'Tolerance threshold updated successfully', 'settings');
            } catch (error) {
                console.error('Error saving tolerance threshold:', error);
                addAlert('error', 'Settings', 'Failed to update tolerance threshold', 'settings');
            }
        }

        // Update tolerance value display when slider changes
        document.getElementById('tolerance-slider').addEventListener('input', function() {
            document.getElementById('tolerance-value').textContent = `${this.value} mm`;
        });

        // Save tolerance when button is clicked
        document.getElementById('save-tolerance').addEventListener('click', saveToleranceThreshold);

        // Load tolerance threshold on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadToleranceThreshold();
            // ... existing code ...
        });

        // --- LED Brightness Control ---
        async function loadLedBrightness() {
            try {
                const response = await fetch('/api/printer/led/brightness');
                const data = await response.json();
                const slider = document.getElementById('led-slider');
                const value = document.getElementById('led-value');
                if (data.brightness != null) {
                    slider.value = data.brightness;
                    value.textContent = `${Math.round(data.brightness)}%`;
                }
            } catch (error) {
                console.error('Error loading LED brightness:', error);
            }
        }

        async function saveLedBrightness() {
            try {
                const slider = document.getElementById('led-slider');
                const brightness = parseFloat(slider.value);
                const response = await fetch('/api/printer/led/brightness', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ brightness }),
                });
                const data = await response.json();
                if (data.status === 'ok') {
                    document.getElementById('led-value').textContent = `${Math.round(data.brightness)}%`;
                }
            } catch (error) {
                console.error('Error saving LED brightness:', error);
            }
        }

        document.getElementById('led-slider').addEventListener('input', function() {
            document.getElementById('led-value').textContent = `${this.value}%`;
        });

        document.getElementById('save-led').addEventListener('click', saveLedBrightness);

        document.addEventListener('DOMContentLoaded', function() {
            loadLedBrightness();
        });

        // Add side menu functionality
        document.getElementById('alerts-toggle').addEventListener('click', function() {
            document.getElementById('alerts-side-menu').classList.add('open');
            document.getElementById('alerts-toggle').style.display = 'none';
        });

        document.getElementById('close-alerts').addEventListener('click', function() {
            document.getElementById('alerts-side-menu').classList.remove('open');
            document.getElementById('alerts-toggle').style.display = '';
        });

        // Alerts state
        let activeAlerts = new Map(); // Store active alerts with their IDs
        let alertEventSource = null; // Store SSE connection

        // Initialize SSE connection for alerts
        function initAlertStream() {
            if (alertEventSource) {
                alertEventSource.close();
                alertEventSource = null;
            }

            try {
                alertEventSource = new EventSource('/api/alerts/stream', { withCredentials: false });
                console.log('Connecting to alert stream...');
                
                alertEventSource.addEventListener('open', function() {
                    console.log('Alert stream connected');
                });
                
                alertEventSource.addEventListener('message', function(event) {
                    try {
                        const alerts = JSON.parse(event.data);
                        updateAlertsFromServer(alerts);
                    } catch (error) {
                        console.error('Error processing alert data:', error);
                    }
                });

                alertEventSource.addEventListener('heartbeat', function(event) {
                    console.log('Received heartbeat from server');
                });

                alertEventSource.addEventListener('error', function(error) {
                    console.error('Alert stream error:', error);
                    if (alertEventSource) {
                        alertEventSource.close();
                        alertEventSource = null;
                    }
                    setTimeout(() => {
                        if (!alertEventSource) {
                            console.log('Attempting to reconnect to alert stream...');
                            initAlertStream();
                        }
                    }, 5000);
                });
            } catch (error) {
                console.error('Error initializing alert stream:', error);
                // Try to reconnect after a delay
                setTimeout(initAlertStream, 5000);
            }
        }

        function updateAlertsFromServer(alerts) {
            const container = document.getElementById('alerts-container');
            const currentIds = new Set(alerts.map(a => a.id));

            Array.from(container.children).forEach(el => {
                const id = el.dataset.alertId;
                if (id && !id.startsWith('local-') && !currentIds.has(id)) {
                    el.remove();
                    activeAlerts.delete(id);
                }
            });

            alerts.forEach(alert => {
                if (alert.resolved_at) {
                    const el = document.querySelector(`[data-alert-id="${alert.id}"]`);
                    if (el) { el.remove(); activeAlerts.delete(alert.id); }
                    return;
                }

                let el = document.querySelector(`[data-alert-id="${alert.id}"]`);
                if (!el && alert.type) {
                    el = document.querySelector(`[data-type="${alert.type}"]`);
                }
                if (!el) {
                    addAlertFromServer(alert);
                } else {
                    el.dataset.alertId = alert.id;
                    el.dataset.type = alert.type;
                    const h4 = el.querySelector('h4');
                    const p = el.querySelector('p');
                    if (h4) h4.textContent = alert.message;
                    if (p) p.textContent = alert.details?.raw_message || '';
                }
            });

            updateAlertCount();
        }

        function addAlertFromServer(alert) {
            const alertsContainer = document.getElementById('alerts-container');
            const noAlertsMessage = document.getElementById('no-alerts-message');
            
            // Skip if alert is already resolved
            if (alert.resolved_at) {
                return;
            }
            
            // Create alert element
            const alertElement = document.createElement('div');
            alertElement.className = `alert-entry alert-${alert.type}`;
            alertElement.dataset.alertId = alert.id;
            alertElement.dataset.type = alert.type;
            
            // Format timestamps
            const createdTime = new Date(alert.created_at).toLocaleTimeString();
            const updatedTime = new Date(alert.updated_at).toLocaleTimeString();
            const occurrences = alert.occurrence_count > 1 ? ` (${alert.occurrence_count}×)` : '';
            const timeDisplay = createdTime === updatedTime ? 
                `Created: ${createdTime}${occurrences}` : 
                `Created: ${createdTime} (Updated: ${updatedTime})${occurrences}`;
            
            // Create alert content (alert text originates from the printer's
            // system log via the server, so it must be escaped before use)
            alertElement.innerHTML = `
                <h4>${escapeHtml(alert.message)}</h4>
                <p>${escapeHtml(alert.details && alert.details.raw_message || '')}</p>
                <span class="alert-timestamp">${escapeHtml(timeDisplay)}</span>
                <button onclick="resolveAlert('${alert.id}')" class="alert-dismiss">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            `;
            
            // Add to container
            alertsContainer.appendChild(alertElement);
            noAlertsMessage.style.display = 'none';
            
            // Store in active alerts map
            activeAlerts.set(alert.id, alert);
        }

        async function resolveAlert(alertId) {
            try {
                await fetch(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
            } catch (e) {
                console.warn('Server-side resolve failed, removing locally:', e);
            }
            const el = document.querySelector(`[data-alert-id="${alertId}"]`);
            if (el) { el.remove(); activeAlerts.delete(alertId); updateAlertCount(); }
        }

        function updateAlertCount() {
            const container = document.getElementById('alerts-container');
            const noAlertsMsg = document.getElementById('no-alerts-message');
            const badge = document.getElementById('alerts-count');
            const clearBtn = document.getElementById('clear-alerts');

            const alerts = container.querySelectorAll('.alert-error, .alert-warning, .alert-info');
            const count = alerts.length;

            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-flex' : 'none';
            if (clearBtn) clearBtn.classList.toggle('hidden', count === 0);

            noAlertsMsg.style.display = count === 0 ? 'block' : 'none';
        }

        // Initialize SSE connection when page loads
        document.addEventListener('DOMContentLoaded', () => {
            // ... existing initialization code ...
            
            // Initialize alert stream
            initAlertStream();
        });

        // Clean up SSE connection when page unloads
        window.addEventListener('beforeunload', () => {
            if (alertEventSource) {
                alertEventSource.close();
                alertEventSource = null;
            }
            if (bed3DAnimId) {
                cancelAnimationFrame(bed3DAnimId);
                bed3DAnimId = null;
            }
            if (bed3DInitialized && bed3DRenderer) {
                bed3DRenderer.dispose();
                bed3DInitialized = false;
            }
        });

        // --- 3D Bed Level Visualization ---
        let bed3DScene, bed3DCamera, bed3DRenderer, bed3DControls;
        let bed3DMesh = null, bed3DWireframe = null;
        let bed3DInitialized = false;
        let bed3DAnimId = null;
        let bed3DProbeData = null;
        let THREE;

        async function initBedLevel3D() {
            if (bed3DInitialized) return;
            const THREE_ = await import('three');
            THREE = THREE_;
            const { Scene, PerspectiveCamera, WebGLRenderer, Color,
                    AmbientLight, DirectionalLight, GridHelper } = THREE;
            const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

            const container = document.getElementById('bed-3d-container');
            if (!container) return;
            document.getElementById('bed-3d-loading')?.remove();

            const isDark = document.documentElement.classList.contains('dark');
            const bgColor = isDark ? 0x1e1e1e : 0xf3f4f6;

            bed3DScene = new Scene();
            bed3DScene.background = new Color(bgColor);

            const aspect = container.clientWidth / container.clientHeight;
            bed3DCamera = new PerspectiveCamera(40, aspect, 1, 1000);
            bed3DCamera.position.set(140, 100, 140);

            bed3DRenderer = new WebGLRenderer({ antialias: true });
            bed3DRenderer.setSize(container.clientWidth, container.clientHeight);
            bed3DRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            container.appendChild(bed3DRenderer.domElement);

            bed3DControls = new OrbitControls(bed3DCamera, bed3DRenderer.domElement);
            bed3DControls.enableDamping = true;
            bed3DControls.dampingFactor = 0.08;
            bed3DControls.minDistance = 30;
            bed3DControls.maxDistance = 400;
            bed3DControls.target.set(0, 0, 0);
            bed3DControls.update();

            const ambient = new AmbientLight(0xffffff, 0.5);
            bed3DScene.add(ambient);
            const dir1 = new DirectionalLight(0xffffff, 0.9);
            dir1.position.set(80, 150, 60);
            bed3DScene.add(dir1);
            const dir2 = new DirectionalLight(0xffffff, 0.3);
            dir2.position.set(-60, 50, -80);
            bed3DScene.add(dir2);

            const gridColor = isDark ? 0x4a4a4a : 0xcccccc;
            const gridHelper = new GridHelper(220, 22, gridColor, gridColor);
            gridHelper.position.y = -0.5;
            bed3DScene.add(gridHelper);

            window.addEventListener('resize', resizeBedLevel3D);

            bed3DInitialized = true;
            animateBedLevel3D();

            if (bed3DProbeData) {
                buildBedSurface3D(bed3DProbeData.measurements, bed3DProbeData.tolerance);
            }
        }

        function animateBedLevel3D() {
            if (!bed3DInitialized) return;
            bed3DAnimId = requestAnimationFrame(animateBedLevel3D);
            bed3DControls.update();
            bed3DRenderer.render(bed3DScene, bed3DCamera);
        }

        function resizeBedLevel3D() {
            const container = document.getElementById('bed-3d-container');
            if (!container || !bed3DRenderer) return;
            const width = container.clientWidth;
            const height = container.clientHeight;
            bed3DRenderer.setSize(width, height);
            bed3DCamera.aspect = width / height;
            bed3DCamera.updateProjectionMatrix();
        }

        function buildBedSurface3D(measurements, tolerance) {
            if (!bed3DInitialized || !measurements || measurements.length < 4) return;
            const { BufferGeometry, Float32BufferAttribute, Mesh, MeshPhongMaterial,
                    EdgesGeometry, LineBasicMaterial, LineSegments } = THREE;

            const uniqueX = [...new Set(measurements.map(p => p.x))].sort((a, b) => a - b);
            const uniqueY = [...new Set(measurements.map(p => p.y))].sort((a, b) => b - a);
            const cols = uniqueX.length;
            const rows = uniqueY.length;
            const centerX = (uniqueX[0] + uniqueX[cols - 1]) / 2;
            const centerY = (uniqueY[0] + uniqueY[rows - 1]) / 2;
            const deviations = measurements.map(p => Math.abs(p.deviation));
            const maxAbsDev = Math.max(...deviations);
            const bedDiagonal = Math.hypot(uniqueX[cols-1] - uniqueX[0], uniqueY[rows-1] - uniqueY[0]);
            const zScale = maxAbsDev > 0.001 ? (bedDiagonal * 0.06) / maxAbsDev : 100;
            const halfTol = tolerance / 2;
            const subDivs = 4;
            const gridVertsX = (cols - 1) * subDivs + 1;
            const gridVertsZ = (rows - 1) * subDivs + 1;

            const positions = [];
            const colors = [];

            for (let iz = 0; iz < gridVertsZ; iz++) {
                for (let ix = 0; ix < gridVertsX; ix++) {
                    const u = ix / (gridVertsX - 1);
                    const v = iz / (gridVertsZ - 1);
                    const worldX = uniqueX[0] + u * (uniqueX[cols - 1] - uniqueX[0]);
                    const worldY = uniqueY[0] + v * (uniqueY[rows - 1] - uniqueY[0]);
                    const cx = worldX - centerX;
                    const cz = worldY - centerY;

                    const gi = Math.min(Math.floor(u * (cols - 1)), cols - 2);
                    const gj = Math.min(Math.floor(v * (rows - 1)), rows - 2);
                    const fu = u * (cols - 1) - gi;
                    const fv = v * (rows - 1) - gj;

                    const p00 = measurements.find(p => p.x === uniqueX[gi] && p.y === uniqueY[gj]);
                    const p10 = measurements.find(p => p.x === uniqueX[gi + 1] && p.y === uniqueY[gj]);
                    const p01 = measurements.find(p => p.x === uniqueX[gi] && p.y === uniqueY[gj + 1]);
                    const p11 = measurements.find(p => p.x === uniqueX[gi + 1] && p.y === uniqueY[gj + 1]);

                    const z00 = p00 ? p00.deviation : 0;
                    const z10 = p10 ? p10.deviation : 0;
                    const z01 = p01 ? p01.deviation : 0;
                    const z11 = p11 ? p11.deviation : 0;

                    const z0 = z00 + (z10 - z00) * fu;
                    const z1 = z01 + (z11 - z01) * fu;
                    const z = (z0 + (z1 - z0) * fv) * zScale;

                    positions.push(cx, z, cz);

                    const absDev = Math.abs(z / zScale);
                    let r, g, b;
                    if (absDev <= halfTol) {
                        const t = absDev / halfTol;
                        r = 0.07 + t * 0.78;
                        g = 0.73 - t * 0.43;
                        b = 0.13 + t * 0.07;
                    } else if (absDev <= tolerance) {
                        const t = (absDev - halfTol) / halfTol;
                        r = 0.85 + t * 0.11;
                        g = 0.70 - t * 0.67;
                        b = 0.05 - t * 0.05;
                    } else {
                        const t = Math.min((absDev - tolerance) / tolerance, 1);
                        r = 0.96 - t * 0.05;
                        g = 0.03 - t * 0.03;
                        b = 0.13 - t * 0.13;
                    }
                    colors.push(Math.max(0, Math.min(1, r)), Math.max(0, Math.min(1, g)), Math.max(0, Math.min(1, b)));
                }
            }

            const indices = [];
            for (let iz = 0; iz < gridVertsZ - 1; iz++) {
                for (let ix = 0; ix < gridVertsX - 1; ix++) {
                    const a = iz * gridVertsX + ix;
                    const b = iz * gridVertsX + ix + 1;
                    const c = (iz + 1) * gridVertsX + ix;
                    const d = (iz + 1) * gridVertsX + ix + 1;
                    indices.push(a, b, c);
                    indices.push(b, d, c);
                }
            }

            if (bed3DMesh) {
                bed3DScene.remove(bed3DMesh);
                bed3DMesh.geometry.dispose();
                bed3DMesh.material.dispose();
                bed3DMesh = null;
            }
            if (bed3DWireframe) {
                bed3DScene.remove(bed3DWireframe);
                bed3DWireframe.geometry.dispose();
                bed3DWireframe.material.dispose();
                bed3DWireframe = null;
            }

            const geometry = new BufferGeometry();
            geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
            geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
            geometry.setIndex(indices);
            geometry.computeVertexNormals();

            const material = new MeshPhongMaterial({
                vertexColors: true,
                shininess: 30,
                specular: 0x222222,
                flatShading: false,
                side: 2
            });
            bed3DMesh = new Mesh(geometry, material);
            bed3DScene.add(bed3DMesh);

            const edges = new EdgesGeometry(geometry);
            const edgeMat = new LineBasicMaterial({
                color: 0x666666, transparent: true, opacity: 0.15
            });
            bed3DWireframe = new LineSegments(edges, edgeMat);
            bed3DScene.add(bed3DWireframe);
        }

        function updateBedLevel3D(measurements, tolerance) {
            bed3DProbeData = { measurements, tolerance };
            if (bed3DInitialized) {
                buildBedSurface3D(measurements, tolerance);
            }
        }

        function switchBedView(view) {
            const vis2d = document.getElementById('bed-visualization');
            const vis3d = document.getElementById('bed-visualization-3d');
            const btn2d = document.getElementById('view-2d-btn');
            const btn3d = document.getElementById('view-3d-btn');

            if (view === '3d') {
                vis2d.classList.add('hidden');
                vis3d.classList.remove('hidden');
                btn2d.classList.remove('active');
                btn3d.classList.add('active');
                initBedLevel3D();
                setTimeout(resizeBedLevel3D, 100);
            } else {
                vis2d.classList.remove('hidden');
                vis3d.classList.add('hidden');
                btn2d.classList.add('active');
                btn3d.classList.remove('active');
            }
        }
