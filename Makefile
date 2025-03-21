.PHONY: shell
shell:
	srun --gpus=1 --mem=40GB --pty apptainer exec --nv igibson_latest.sif bash	