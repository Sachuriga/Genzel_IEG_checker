import os
import glob
import re  # Added for flexible splitting
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
import sys
import random

# --- GUI IMPORTS ---
from PyQt5.QtWidgets import QApplication, QFileDialog, QInputDialog
from matplotlib.widgets import Slider

class ImageReviewer:
    def __init__(self):
        self.results = []
        self.current_index = 0
        
        self.score_mapping = {
            '1': -2, 
            '2': -1, 
            '3': 0, 
            '4': 1, 
            '5': 2,
            '6': 'DISCARD'
        }
        
        self.img_height = 0
        self.img_width = 0
        self.ax_dict = {} 

        # --- PHASE 1: Locate Regions File Automatically ---
        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.regions_file_path = os.path.join(script_dir, "Regions.xlsx")

        if not os.path.exists(self.regions_file_path):
            print(f"\nCRITICAL ERROR: Could not find 'Regions.xlsx'")
            print(f"Looking in: {script_dir}")
            return

        # Load regions once and store them
        self.target_regions_list = self.load_target_regions()
        
        # --- PHASE 2: Get Inputs (PyQt5) ---
        self.folder_path, self.rat_name = self.get_user_inputs_qt()

        if not self.folder_path or not self.rat_name:
            print("Missing inputs. Exiting.")
            return

        self.output_path = os.path.join(self.folder_path, f"{self.rat_name}_QC_Scores.xlsx")

        # --- PHASE 3: Start Review ---
        self.find_image_pairs()

    @staticmethod
    def get_user_inputs_qt():
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        print("Please select the Image Folder in the pop-up...")
        folder_path = QFileDialog.getExistingDirectory(None, "Select Image Folder")
        if not folder_path: return None, None
        
        rat_name, ok = QInputDialog.getText(None, "Input Required", "Enter Rat Name (e.g., Rat461707):")
        if not ok or not rat_name: return None, None
        
        return folder_path, rat_name

    def load_target_regions(self):
        try:
            df = pd.read_excel(self.regions_file_path, header=None)
            region_list = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
            # Sort by length (longest first) to match specific regions before general ones
            region_list.sort(key=len, reverse=True)
            return region_list
        except Exception as e:
            print(f"Error reading 'Regions.xlsx': {e}")
            return []

    # --- NEW HELPER FUNCTION TO REPLACE PARTS[7] ---
    def extract_metadata(self, filename):
        """
        Parses filename to find Region and Hemisphere regardless of position.
        Returns: (Region, Hemisphere) or (None, None)
        """
        name_no_ext = os.path.splitext(filename)[0]
        
        # Split by underscore, dash, or space
        tokens = re.split(r'[_\-\s]+', name_no_ext)
        
        # 1. Find Hemisphere
        hemi = None
        if "RH" in tokens:
            hemi = "RH"
        elif "LH" in tokens:
            hemi = "LH"

        # 2. Find Region
        found_region = None
        for region in self.target_regions_list:
            # Check if the region string exists exactly in the tokens
            if region in tokens:
                found_region = region
                break
        
        return found_region, hemi

    def find_image_pairs(self):
        if not self.target_regions_list:
            print("CRITICAL ERROR: 'Regions.xlsx' appears to be empty or unreadable.")
            return

        print(f"--- Loaded Target Regions ---")
        print(f"Targets: {self.target_regions_list}")

        search_pattern = os.path.join(self.folder_path, f"*{self.rat_name}*.tif")
        all_tif_files = glob.glob(search_pattern)
        
        print(f"Scanning {self.folder_path}...")
        
        grouped_files = {}

        for tif_path in all_tif_files:
            file_name = os.path.basename(tif_path)
            
            # --- UPDATED: Use the new helper function ---
            region, hemisphere = self.extract_metadata(file_name)

            # If we couldn't find a valid region or RH/LH, skip the file
            if not region or not hemisphere:
                continue

            # Group the files
            if region not in grouped_files:
                grouped_files[region] = {'RH': [], 'LH': []}
            
            if hemisphere == "RH":
                grouped_files[region]['RH'].append(tif_path)
            elif hemisphere == "LH":
                grouped_files[region]['LH'].append(tif_path)

        selected_tif_files = []
        
        for uid, data in grouped_files.items():
            rh_list = data['RH']
            lh_list = data['LH']
            
            count_rh = min(len(rh_list), 1) 
            count_lh = min(len(lh_list), 1)
            
            if count_rh > 0:
                selected_tif_files.extend(random.sample(rh_list, count_rh))
            if count_lh > 0:
                selected_tif_files.extend(random.sample(lh_list, count_lh))
        
        print(f"--- Total images selected: {len(selected_tif_files)} ---\n")
        
        self.valid_pairs = []
        for tif_path in selected_tif_files:
            base_name = os.path.splitext(tif_path)[0]
            jpg_path_guess_1 = f"{base_name}_Object Predictions.jpeg"
            jpg_path_guess_2 = f"{base_name}_Object Predictions.jpg"
            
            final_jpg_path = None
            if os.path.exists(jpg_path_guess_1): final_jpg_path = jpg_path_guess_1
            elif os.path.exists(jpg_path_guess_2): final_jpg_path = jpg_path_guess_2
            
            if final_jpg_path: self.valid_pairs.append((tif_path, final_jpg_path))

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
            self.original_tif_arr = np.array(tif_img)
            
            jpg_img = Image.open(jpg_path).convert('L')
            if jpg_img.size != tif_img.size: 
                jpg_img = jpg_img.resize(tif_img.size, Image.NEAREST)
            jpg_arr_gray = np.array(jpg_img)
            
            self.img_height, self.img_width = self.original_tif_arr.shape[:2]
        except Exception as e:
            print(f"Error loading {file_name}: {e}")
            self.current_index += 1
            self.show_next_image()
            return

        # Setup Plot Layout
        layout = [['overlap', 'jpeg'], ['overlap', 'tif']]
        self.fig, self.ax_dict = plt.subplot_mosaic(layout, figsize=(15, 9))
        
        plt.subplots_adjust(left=0.05, right=0.95, top=0.9, bottom=0.20, wspace=0.2, hspace=0.2)
        
        manager = plt.get_current_fig_manager()
        try: manager.window.showMaximized()
        except: pass

        self.fig.canvas.manager.set_window_title(f"Image {self.current_index + 1}/{len(self.valid_pairs)}: {file_name}")

        # --- UPDATED: Get Title Info safely ---
        region_name, hemi_name = self.extract_metadata(file_name)
        if not region_name: region_name = "Unknown"
        if not hemi_name: hemi_name = "??"

        # --- IMAGE PLOTS ---
        self.im_overlap = self.ax_dict['overlap'].imshow(self.original_tif_arr)
        self.ax_dict['overlap'].contour(jpg_arr_gray, levels=[127], colors='red', linewidths=.75)
        
        title_text = (
            f"Region: {region_name} ({hemi_name})\n"
            f"SCORES: [1 = -2] [2 = -1] [3 = 0] [4 = +1] [5 = +2] [6 = DISCARD]\n"
            f"CONTROLS: Scroll=Zoom | 'r'=Reset | Sliders=Adjust"
        )
        self.ax_dict['overlap'].set_title(title_text, fontsize=12, color='blue', fontweight='bold')
        self.ax_dict['overlap'].axis('off')

        self.ax_dict['jpeg'].imshow(jpg_arr_gray, cmap='gray')
        self.ax_dict['jpeg'].set_title("Prediction Mask", fontsize=10)
        self.ax_dict['jpeg'].axis('off')

        self.im_tif = self.ax_dict['tif'].imshow(self.original_tif_arr)
        self.ax_dict['tif'].set_title("Original TIF (Adjustable)", fontsize=10)
        self.ax_dict['tif'].axis('off')

        # --- SLIDERS ---
        ax_contrast = plt.axes([0.25, 0.08, 0.5, 0.03])
        ax_brightness = plt.axes([0.25, 0.04, 0.5, 0.03])

        self.s_contrast = Slider(ax_contrast, 'Contrast', 0.1, 3.0, valinit=1.0)
        self.s_brightness = Slider(ax_brightness, 'Brightness', -100, 100, valinit=0)

        self.s_contrast.on_changed(self.update_image_display)
        self.s_brightness.on_changed(self.update_image_display)

        # Connect Events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        plt.show()

    def update_image_display(self, val):
        c = self.s_contrast.val
        b = self.s_brightness.val
        temp_img = self.original_tif_arr.astype(float)
        temp_img = temp_img * c + b
        temp_img = np.clip(temp_img, 0, 255).astype(np.uint8)
        self.im_overlap.set_data(temp_img)
        self.im_tif.set_data(temp_img)
        self.fig.canvas.draw_idle()

    def apply_zoom(self, scale_factor, center_x, center_y, ref_ax):
        cur_xlim = ref_ax.get_xlim()
        cur_ylim = ref_ax.get_ylim()

        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[0] - cur_ylim[1]) * scale_factor 

        relx = (cur_xlim[1] - center_x) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[0] - center_y) / (cur_ylim[0] - cur_ylim[1])

        new_xlim = [center_x - new_width * (1-relx), center_x + new_width * relx]
        new_ylim = [center_y + new_height * (1-rely), center_y - new_height * rely]

        for key, ax in self.ax_dict.items():
            if key in ['overlap', 'jpeg', 'tif']:
                ax.set_xlim(new_xlim)
                ax.set_ylim(new_ylim)
        self.fig.canvas.draw_idle()

    def on_scroll(self, event):
        if event.inaxes is None: return
        if event.inaxes not in self.ax_dict.values(): return 
        base_scale = 1.2
        scale_factor = 1 / base_scale if event.button == 'up' else base_scale
        self.apply_zoom(scale_factor, event.xdata, event.ydata, event.inaxes)

    def on_key_press(self, event):
        if event.key in self.score_mapping:
            score = self.score_mapping[event.key]
            current_file = os.path.basename(self.valid_pairs[self.current_index][0])
            
            # --- UPDATED: Use the new helper function ---
            region_str, hemi_str = self.extract_metadata(current_file)
            
            if not region_str: region_str = "Unknown"
            if not hemi_str: hemi_str = "Unknown"

            print(f"Scored {score} for {current_file}")
            
            self.results.append({
                'Filename': current_file, 
                'Rat_ID': self.rat_name,
                'Region': region_str,
                'Hemisphere': hemi_str,
                'Score': score, 
                'Raw_Input': event.key
            })
            
            self.save_progress()
            plt.close(self.fig)
            self.current_index += 1
            self.show_next_image()

        elif event.key == 'escape':
            print("Stopped by user.")
            plt.close(self.fig)

        elif event.key == 'r':
            self.reset_view()

        elif event.key in ['i', 'o']:
            base_scale = 1.2
            scale_factor = 1 / base_scale if event.key == 'i' else base_scale
            if event.inaxes and event.inaxes in self.ax_dict.values():
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
        for key, ax in self.ax_dict.items():
            if key in ['overlap', 'jpeg', 'tif']:
                ax.set_xlim(default_xlim)
                ax.set_ylim(default_ylim)
        self.s_contrast.reset()
        self.s_brightness.reset()
        self.fig.canvas.draw_idle()

    def save_progress(self):
        if not self.results: return
        try: 
            df = pd.DataFrame(self.results)
            cols = ['Filename', 'Rat_ID', 'Region', 'Hemisphere', 'Score', 'Raw_Input']
            df = df[cols]
            df.to_excel(self.output_path, index=False)
        except Exception as e: 
            print(f"WARNING: Save failed: {e}")

if __name__ == "__main__":
    app = ImageReviewer()