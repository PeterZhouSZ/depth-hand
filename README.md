# Hand in Depth

> Single view depth image based hand detection and pose estimation.

## Install

```
```

## Usage

```
cd code
python -m train.evaluate \
    --data_root=/data \
    --out_root=/output \
    --max_epoch=1 --batch_size=5 --bn_decay=0.9 \
    --show_draw=True --model_name=base_clean
```
