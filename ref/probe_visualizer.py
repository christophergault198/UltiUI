import sys
import json
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QPushButton, QFileDialog, QLabel, QTextEdit, QTabWidget)
from PySide6.QtCore import Qt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from temp_flow_visualizer import TempFlowVisualizer

class ProbeVisualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ultimaker S3 Probe Report Visualizer")
        self.setGeometry(100, 100, 1200, 800)  # Made window larger
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create Bed Leveling tab
        self.bed_leveling_tab = QWidget()
        bed_leveling_layout = QVBoxLayout(self.bed_leveling_tab)
        
        # Create matplotlib figure for bed leveling
        self.bed_figure = Figure(figsize=(8, 6))
        self.bed_canvas = FigureCanvas(self.bed_figure)
        bed_leveling_layout.addWidget(self.bed_canvas)
        
        # Create analysis text area
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setMinimumHeight(150)
        self.analysis_text.setStyleSheet("""
            QTextEdit {
                background-color: #f0f0f0;
                color: #000000;
                font-family: Arial;
                font-size: 12px;
                padding: 8px;
                border: 1px solid #cccccc;
                border-radius: 4px;
            }
        """)
        bed_leveling_layout.addWidget(self.analysis_text)
        
        # Create Temperature & Flow tab using the new visualizer
        self.temp_flow_visualizer = TempFlowVisualizer()
        
        # Add tabs to tab widget
        self.tab_widget.addTab(self.bed_leveling_tab, "Bed Leveling")
        self.tab_widget.addTab(self.temp_flow_visualizer, "Temperature & Flow")
        
        # Create load buttons
        self.load_probe_button = QPushButton("Load Probe Report")
        self.load_probe_button.clicked.connect(self.load_probe_report)
        layout.addWidget(self.load_probe_button)
        
        self.load_temp_button = QPushButton("Load Temperature & Flow Data")
        self.load_temp_button.clicked.connect(self.load_temp_flow_data)
        layout.addWidget(self.load_temp_button)
        
        # Create status label
        self.status_label = QLabel("No data loaded")
        layout.addWidget(self.status_label)
        
        # Initialize data
        self.probe_data = None
        self.annotation = None
        
        # Connect mouse events
        self.bed_canvas.mpl_connect('motion_notify_event', self.on_hover)
        
    def analyze_bed_leveling(self, points, z_values):
        """Analyze bed leveling data and provide insights."""
        z_min = np.min(z_values)
        z_max = np.max(z_values)
        z_variance = z_max - z_min
        z_mean = np.mean(z_values)
        z_std = np.std(z_values)
        
        # Convert points to numpy array for easier analysis
        points = np.array(points)
        
        # Find locations of min and max points
        min_idx = np.argmin(z_values)
        max_idx = np.argmax(z_values)
        min_point = points[min_idx]
        max_point = points[max_idx]
        
        # Analyze bed tilt
        x_correlation = np.corrcoef(points[:, 0], z_values)[0, 1]
        y_correlation = np.corrcoef(points[:, 1], z_values)[0, 1]
        
        # Generate analysis text
        analysis = []
        analysis.append("=== Bed Leveling Analysis ===\n")
        
        # Overall assessment
        if z_variance < 0.1:
            analysis.append("✅ Bed is well-leveled (variance < 0.1mm)")
        elif z_variance < 0.2:
            analysis.append("⚠️ Bed leveling is acceptable but could be improved")
        else:
            analysis.append("❌ Bed requires leveling attention (variance > 0.2mm)")
        
        analysis.append(f"\nMeasurements:")
        analysis.append(f"• Variance: {z_variance:.3f}mm (Max-Min difference)")
        analysis.append(f"• Average height: {z_mean:.3f}mm")
        analysis.append(f"• Standard deviation: {z_std:.3f}mm")
        
        analysis.append("\nKey Points:")
        analysis.append(f"• Highest point: {z_max:.3f}mm at X:{max_point[0]:.1f}, Y:{max_point[1]:.1f}")
        analysis.append(f"• Lowest point: {z_min:.3f}mm at X:{min_point[0]:.1f}, Y:{min_point[1]:.1f}")
        
        analysis.append("\nRecommendations:")
        if abs(x_correlation) > 0.3 or abs(y_correlation) > 0.3:
            if abs(x_correlation) > abs(y_correlation):
                if x_correlation > 0:
                    analysis.append("• Bed appears tilted up towards the right side")
                    analysis.append("  → Adjust right side leveling screws slightly lower")
                else:
                    analysis.append("• Bed appears tilted up towards the left side")
                    analysis.append("  → Adjust left side leveling screws slightly lower")
            else:
                if y_correlation > 0:
                    analysis.append("• Bed appears tilted up towards the back")
                    analysis.append("  → Adjust back leveling screws slightly lower")
                else:
                    analysis.append("• Bed appears tilted up towards the front")
                    analysis.append("  → Adjust front leveling screws slightly lower")
        
        if z_variance > 0.1:
            if z_variance > 0.2:
                analysis.append("• Perform a complete bed leveling procedure")
                analysis.append("• Focus on the areas with extreme values first")
            else:
                analysis.append("• Fine-tune the leveling near the highest and lowest points")
        
        if z_std > 0.1:
            analysis.append("• Check for debris or buildup on the bed surface")
            analysis.append("• Consider cleaning the bed with IPA")
        
        return "\n".join(analysis)
    
    def on_hover(self, event):
        if not hasattr(self, 'scatter') or not self.scatter or not event.inaxes:
            return
            
        cont, ind = self.scatter.contains(event)
        if cont:
            pos = self.scatter.get_offsets()[ind["ind"][0]]
            z_val = self.z_values[ind["ind"][0]]
            
            # Remove previous annotation if it exists
            if self.annotation:
                self.annotation.remove()
            
            # Create new annotation
            self.annotation = event.inaxes.annotate(
                f'X: {pos[0]:.1f}\nY: {pos[1]:.1f}\nZ: {z_val:.3f}',
                xy=(pos[0], pos[1]), xycoords='data',
                xytext=(10, 10), textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0')
            )
            
            self.bed_canvas.draw_idle()
        elif self.annotation:
            self.annotation.remove()
            self.annotation = None
            self.bed_canvas.draw_idle()
    
    def load_probe_report(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Probe Report",
            "",
            "JSON Files (*.json)"
        )
        
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    self.probe_data = json.load(f)
                self.visualize_probe_data()
                self.status_label.setText(f"Loaded probe report: {file_name}")
                self.tab_widget.setCurrentIndex(0)  # Switch to bed leveling tab
            except Exception as e:
                self.status_label.setText(f"Error loading probe report: {str(e)}")
    
    def load_temp_flow_data(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Temperature & Flow Data",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )
        
        if file_name:
            success, message = self.temp_flow_visualizer.load_data(file_name)
            self.status_label.setText(message)
            if success:
                self.tab_widget.setCurrentIndex(1)  # Switch to temperature & flow tab
    
    def visualize_probe_data(self):
        if not self.probe_data:
            return
            
        # Clear previous plot
        self.bed_figure.clear()
        
        # Create subplot
        ax = self.bed_figure.add_subplot(111)
        
        # Extract probe points
        points = []
        z_values = []
        
        # Get the first probe report (assuming it's the most recent)
        report = self.probe_data["0"]
        probe_points = report["_ProbeReport__probe_points"]
        
        for point in probe_points:
            location = point["_ProbePoint__location"]
            x = location["_Vector2__x"]
            y = location["_Vector2__y"]
            z = point["_ProbePoint__z_offset_from_bed_zero"]
            
            points.append([x, y])
            z_values.append(z)
        
        points = np.array(points)
        self.z_values = np.array(z_values)  # Store z_values as instance variable
        
        # Calculate statistics
        z_min = np.min(self.z_values)
        z_max = np.max(self.z_values)
        z_variance = np.max(self.z_values) - np.min(self.z_values)
        
        # Create scatter plot
        self.scatter = ax.scatter(points[:, 0], points[:, 1], c=self.z_values, 
                                cmap='viridis', s=100)
        
        # Add colorbar
        self.bed_figure.colorbar(self.scatter, ax=ax, label='Z Offset (mm)')
        
        # Set labels and title
        ax.set_xlabel('X Position (mm)')
        ax.set_ylabel('Y Position (mm)')
        ax.set_title('Bed Leveling Probe Points')
        
        # Add statistics text
        stats_text = f'Min Z: {z_min:.3f} mm\nMax Z: {z_max:.3f} mm\nVariance: {z_variance:.3f} mm'
        ax.text(0.02, 0.98, stats_text,
                transform=ax.transAxes,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        # Set equal aspect ratio
        ax.set_aspect('equal')
        
        # Add grid
        ax.grid(True)
        
        # Update canvas
        self.bed_canvas.draw()
        
        # Update analysis text
        analysis = self.analyze_bed_leveling(points, self.z_values)
        self.analysis_text.setText(analysis)

def main():
    app = QApplication(sys.argv)
    window = ProbeVisualizer()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 