import os
import glob
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
import sys
import random

# --- GUI IMPORTS (PyQt5) ---
from PyQt5.QtWidgets import QApplication, QFileDialog, QInputDialog

class ImageReviewer:
    def __init__(self):
        self.results = []
        self.current_index = 0
        self.score_mapping = {'1': -2, '2': -1, '3': 0, '4': 1, '5': 2}
        
        # Store current image dimensions for Reset functionality
        self.img_height = 0
        self.img_width = 0
        self.ax_dict = {} 

        # --- PHASE 1: Get Inputs (PyQt5) ---
        self.folder_path, self.rat_name = self.get_user_inputs_qt()

        if not self.folder_path or not self.rat_name:
            print("Missing inputs. Exiting.")
            return

        self.output_path = os.path.join(self.folder_path, f"{self.rat_name}_QC_Scores.xlsx")

        # --- PHASE 2: Start Review ---
        self.find_image_pairs()

    @staticmethod
    def get_user_inputs_qt():
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        print("Please select the folder in the dialog window...")
        folder_path = QFileDialog.getExistingDirectory(None, "Select Image Folder")
        if not folder_path: return None, None
        
        rat_name, ok = QInputDialog.getText(None, "Input Required", "Enter Rat Name (e.g., Rat461707):")
        if not ok or not rat_name: return None, None
        
        return folder_path, rat_name

    def find_image_pairs(self):
        # 1. Define Target Regions (Whitelist)
        target_regions = ['PrL', 'CA3', 'CA1', 'ACC', 'DG']
        print(f"Targeting ONLY these regions: {target_regions}")

        # 2. Scan for all TIF files
        search_pattern = os.path.join(self.folder_path, f"*{self.rat_name}*.tif")
        all_tif_files = glob.glob(search_pattern)
        
        print(f"Scanning {self.folder_path}...")
        print(f"Found total {len(all_tif_files)} files initially. Filtering now...")

        # --- Filtering Logic ---
        grouped_files = {}

        for tif_path in all_tif_files:
            file_name = os.path.basename(tif_path)
            
            # Remove extension to ensure clean splitting
            name_no_ext = os.path.splitext(file_name)[0]
            parts = name_no_ext.split("_")
            
            # Safety check: Ensure filename has enough parts
            if len(parts) <= 8:
                continue

            # Extract Metadata
            unique_id = parts[7]  # Region (e.g., PrL, CA1)
            hemisphere = parts[8] # Hemisphere (LH or RH)

            # Filter: Skip if not in target regions
            if unique_id not in target_regions:
                continue

            if unique_id not in grouped_files:
                grouped_files[unique_id] = {'RH': [], 'LH': []}
            
            if hemisphere == "RH":
                grouped_files[unique_id]['RH'].append(tif_path)
            elif hemisphere == "LH":
                grouped_files[unique_id]['LH'].append(tif_path)

        # 3. Random Sampling (2 RH + 2 LH per region)
        selected_tif_files = []
        
        print("\n--- Selection Summary ---")
        if not grouped_files:
            print("WARNING: No images matched the target regions. Check filenames.")

        for uid, data in grouped_files.items():
            rh_list = data['RH']
            lh_list = data['LH']
            
            count_rh = min(len(rh_list), 1)
            count_lh = min(len(lh_list), 1)
            
            print(f"Region [{uid}]: Selecting {count_rh} RH and {count_lh} LH images.")
            
            if count_rh > 0:
                selected_tif_files.extend(random.sample(rh_list, count_rh))
            if count_lh > 0:
                selected_tif_files.extend(random.sample(lh_list, count_lh))
        
        print(f"--- Total images selected for review: {len(selected_tif_files)} ---\n")
        
        # 4. Pair with Prediction Images
        self.valid_pairs = []
        
        for tif_path in selected_tif_files:
            base_name = os.path.splitext(tif_path)[0]
            jpg_path_guess_1 = f"{base_name}_Object Predictions.jpeg"
            jpg_path_guess_2 = f"{base_name}_Object Predictions.jpg"
            
            final_jpg_path = None
            if os.path.exists(jpg_path_guess_1): final_jpg_path = jpg_path_guess_1
            elif os.path.exists(jpg_path_guess_2): final_jpg_path = jpg_path_guess_2
            
            if final_jpg_path: self.valid_pairs.append((tif_path, final_jpg_path))
            else: print(f"Warning: No prediction JPEG found for {os.path.basename(tif_path)}")

        if self.valid_pairs: 
            self.show_next_image()
        else: 
            print("No valid pairs found.")

    def show_next_image(self):
        if self.current_index >= len(self.valid_pairs):
            print("\nAll images reviewed.")
            print(f"File saved: {self.output_path}")
            sys.exit(0)

        tif_path, jpg_path = self.valid_pairs[self.current_index]
        file_name = os.path.basename(tif_path)

        try:
            # Load Images
            tif_img = Image.open(tif_path).convert('RGB')
            tif_arr = np.array(tif_img)
            
            jpg_img = Image.open(jpg_path).convert('L')
            if jpg_img.size != tif_img.size: 
                jpg_img = jpg_img.resize(tif_img.size, Image.NEAREST)
            jpg_arr_gray = np.array(jpg_img)
            
            self.img_height, self.img_width = tif_arr.shape[:2]
        except Exception as e:
            print(f"Error loading {file_name}: {e}")
            self.current_index += 1
            self.show_next_image()
            return

        # Setup Plot Layout
        layout = [['overlap', 'jpeg'], ['overlap', 'tif']]
        self.fig, self.ax_dict = plt.subplot_mosaic(layout, figsize=(15, 9), constrained_layout=True)
        
        # Maximize Window
        manager = plt.get_current_fig_manager()
        try: manager.window.showMaximized()
        except: pass

        self.fig.canvas.manager.set_window_title(f"Image {self.current_index + 1}/{len(self.valid_pairs)}: {file_name}")

        # Extract Region info for display
        clean_name = os.path.splitext(file_name)[0]
        region_name = clean_name.split('_')[7]
        hemi_name = clean_name.split('_')[8]

        # --- MAIN OVERLAP PLOT ---
        self.ax_dict['overlap'].imshow(tif_arr)
        self.ax_dict['overlap'].contour(jpg_arr_gray, levels=[127], colors='red', linewidths=.75)
        
        # Detailed Title with Scores
        title_text = (
            f"Region: {region_name} ({hemi_name})\n"
            f"SCORES: [1 = -2]  [2 = -1]  [3 = 0]  [4 = +1]  [5 = +2]\n"
            f"CONTROLS: Scroll or i/o = Zoom | 'r' = Reset"
        )
        
        self.ax_dict['overlap'].set_title(title_text, fontsize=12, color='blue', fontweight='bold')
        self.ax_dict['overlap'].axis('off')

        # --- SUBPLOTS ---
        self.ax_dict['jpeg'].imshow(jpg_arr_gray, cmap='gray')
        self.ax_dict['jpeg'].set_title("Prediction Mask", fontsize=10)
        self.ax_dict['jpeg'].axis('off')

        self.ax_dict['tif'].imshow(tif_arr)
        self.ax_dict['tif'].set_title("Original TIF", fontsize=10)
        self.ax_dict['tif'].axis('off')

        # Connect Events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        plt.show()

    def apply_zoom(self, scale_factor, center_x, center_y, ref_ax):
        cur_xlim = ref_ax.get_xlim()
        cur_ylim = ref_ax.get_ylim()

        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[0] - cur_ylim[1]) * scale_factor 

        relx = (cur_xlim[1] - center_x) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[0] - center_y) / (cur_ylim[0] - cur_ylim[1])

        new_xlim = [center_x - new_width * (1-relx), center_x + new_width * relx]
        new_ylim = [center_y + new_height * (1-rely), center_y - new_height * rely]

        for ax in self.ax_dict.values():
            ax.set_xlim(new_xlim)
            ax.set_ylim(new_ylim)
        
        self.fig.canvas.draw_idle()

    def on_scroll(self, event):
        if event.inaxes is None: return
        base_scale = 1.2
        scale_factor = 1 / base_scale if event.button == 'up' else base_scale
        self.apply_zoom(scale_factor, event.xdata, event.ydata, event.inaxes)

    def on_key_press(self, event):
        # 1. Scoring Logic
        if event.key in self.score_mapping:
            score = self.score_mapping[event.key]
            current_file = os.path.basename(self.valid_pairs[self.current_index][0])
            
            # Extract metadata for Excel
            clean_name = os.path.splitext(current_file)[0]
            parts = clean_name.split("_")
            region_str = parts[7]
            hemi_str = parts[8]

            print(f"Scored {score} for {current_file}")
            
            self.results.append({
                'Filename': current_file, 
                'Rat_ID': self.rat_name,
                'Region': region_str,     # Added to Excel
                'Hemisphere': hemi_str,   # Added to Excel
                'Score': score, 
                'Raw_Input': event.key
            })
            
            self.save_progress()
            plt.close(self.fig)
            self.current_index += 1
            self.show_next_image()

        # 2. Exit
        elif event.key == 'escape':
            print("Stopped by user.")
            plt.close(self.fig)

        # 3. Reset View
        elif event.key == 'r':
            self.reset_view()

        # 4. Keyboard Zoom (i/o)
        elif event.key in ['i', 'o']:
            base_scale = 1.2
            if event.key == 'i': # In
                scale_factor = 1 / base_scale
            else: # Out
                scale_factor = base_scale

            if event.inaxes:
                center_x, center_y = event.xdata, event.ydata
                ref_ax = event.inaxes
            else:
                ref_ax = self.ax_dict['overlap']
                xlim = ref_ax.get_xlim()
                ylim = ref_ax.get_ylim()
                center_x = (xlim[0] + xlim[1]) / 2
                center_y = (ylim[0] + ylim[1]) / 2

            self.apply_zoom(scale_factor, center_x, center_y, ref_ax)

    def reset_view(self):
        default_xlim = (-0.5, self.img_width - 0.5)
        default_ylim = (self.img_height - 0.5, -0.5)
        for ax in self.ax_dict.values():
            ax.set_xlim(default_xlim)
            ax.set_ylim(default_ylim)
        self.fig.canvas.draw_idle()

    def save_progress(self):
        if not self.results: return
        try: 
            # Reorder columns for better readability
            df = pd.DataFrame(self.results)
            cols = ['Filename', 'Rat_ID', 'Region', 'Hemisphere', 'Score', 'Raw_Input']
            df = df[cols]
            df.to_excel(self.output_path, index=False)
        except Exception as e: 
            print(f"WARNING: Save failed: {e}")

if __name__ == "__main__":
    app = ImageReviewer()