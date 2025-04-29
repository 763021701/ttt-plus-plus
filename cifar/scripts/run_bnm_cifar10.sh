#! /usr/bin/env bash

export PYTHONPATH=$PYTHONPATH:$(pwd)

DATASET=cifar10

# ===================================

LEVEL=5

if [ "$#" -lt 2 ]; then
	CORRUPT=snow
	# CORRUPT=cifar_new

	METHOD=bnm
	NSAMPLE=100000
else
	CORRUPT=$1
	METHOD=$2
	NSAMPLE=$3
fi

# ===================================


LR=0.001
BS_BNM=128

echo 'DATASET: '${DATASET}
echo 'CORRUPT: '${CORRUPT}
echo 'METHOD:' ${METHOD}
echo 'LR:' ${LR}
echo 'BS_BNM:' ${BS_BNM}
echo 'NSAMPLE:' ${NSAMPLE}

# ===================================

printf '\n---------------------\n\n'

python bnm.py \
	--dataroot ${DATADIR} \
	--resume results/${DATASET}_joint_resnet50 \
	--outf results/${DATASET}_bnm_joint_resnet50 \
	--corruption ${CORRUPT} \
	--level ${LEVEL} \
	--workers 12 \
	--batch_size ${BS_BNM} \
	--lr ${LR} \
	--num_sample ${NSAMPLE} \
	--tsne
