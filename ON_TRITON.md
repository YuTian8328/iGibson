# iGibson Setup On Triton

## 1. Clone the Repository
```bash
git clone --depth 1 https://github.com/StanfordVL/iGibson ./iGibson --recursive
cd iGibson
```

## 2. Pull the Image
```bash
apptainer pull docker://igibson/igibson:latest
```

## 3. Run the Container on a GPU Node with Enough Memory
```bash
srun --gpus=1 --mem=40GB --pty apptainer exec --nv igibson_latest.sif bash	
```
or 
```bash
make shell # if you have a Makefile managing commonly used commands like what I have in this directory
```

## 4. Install the igibson package
```bash
pip install --no-cache-dir -e .
```

## 5. Download the Assets
```bash
python -m igibson.utils.assets_utils --download_assets
python -m igibson.utils.assets_utils --download_demo_data
```

## 6. Modify GPU Device Detection
Edit `igibson/render/mesh_renderer/get_available_devices.py` to handle GPU detection more robustly:

```diff
// ... existing code ...
     for i in range(num_devices):
-        output = subprocess.check_output(["nvidia-smi", "-q", "-i", str(i)])
-        output_list = output.decode("utf-8").split("\n")
-        output_list = [item for item in output_list if "Minor" in item]
-        num = int(output_list[0].split(":")[-1])
-        if num == minor_idx:
-            return i
+        try:
+            output = subprocess.check_output(["nvidia-smi", "-q", "-i", str(i)])
+            output_list = output.decode("utf-8").split("\n")
+            output_list = [item for item in output_list if "Minor" in item]
+            num = int(output_list[0].split(":")[-1])
+            if num == minor_idx:
+                return i
+        except subprocess.CalledProcessError as e:
+            if i == 0:
+                return 0  # Return 0 if we can't query the first GPU
+            continue
     return 0
// ... existing code ...
```

## 7. Run the Benchmark
```bash
python -m tests.benchmark.benchmark_static_scene
```

