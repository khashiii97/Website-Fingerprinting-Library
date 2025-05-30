import os
import sys
import json
import time
import torch
import random
import argparse
import numpy as np
from WFlib import models
from WFlib.tools import data_processor, model_utils, parser_utils
import warnings
warnings.filterwarnings("ignore")

# Set a fixed seed for reproducibility
fix_seed = 2024
random.seed(fix_seed)
torch.manual_seed(fix_seed)
np.random.seed(fix_seed)

# Argument parser for command-line options, arguments, and sub-commands
parser = argparse.ArgumentParser(description="WFlib")
parser.add_argument("--dataset", type=str, required=True, default="CW", help="Dataset name")
parser.add_argument("--model", type=str, required=True, default="DF", help="Model name")
parser.add_argument("--device", type=str, default="cpu", help="Device, options=[cpu, cuda, cuda:x]")
parser.add_argument("--num_tabs", type=int, default=1, 
                    help="Maximum number of tabs opened by users while browsing")
parser.add_argument("--scenario", type=str, default="Closed-world", 
                    help="Attack scenario, options=[Closed-world, Open-world]")

# Input parameters
parser.add_argument("--valid_file", type=str, default="valid", help="Valid file")
parser.add_argument("--test_file", type=str, default="test", help="Test file")
parser.add_argument("--feature", type=str, default="DIR", help="Feature type, options=[DIR, DT, DT2, TAM, TAF]")
parser.add_argument("--seq_len", type=int, default=5000, help="Input sequence length")

# Optimization parameters
parser.add_argument("--num_workers", type=int, default=10, help="Data loader num workers")
parser.add_argument("--batch_size", type=int, default=256, help="Batch size of train input data")

# Output parameters
parser.add_argument("--eval_method", type=str, default="common", help="Method used in the evaluation, options=[common, kNN, holmes]")
parser.add_argument('--eval_metrics', nargs='+', required=True, type=str, 
                    help="Evaluation metrics, options=[Accuracy, Precision, Recall, F1-score, P@min, r-Precision]")
parser.add_argument("--log_path", type=str, default="./logs/", help="Log path")
parser.add_argument("--checkpoints", type=str, default="./checkpoints/", help="Location of model checkpoints")
parser.add_argument("--load_name", type=str, default="base", help="Name of the model file")
parser.add_argument("--result_file", type=str, default="result", help="File to save test results")
parser.add_argument('-cc', '--compute_canada', type=parser_utils.str2bool, nargs='?', const=True, default=False,
                         help='Whether we are using compute canada')
parser.add_argument('--random_labels', type=parser_utils.str2bool, nargs='?', const=True, default=False,
                         help='Wether we want to assign random labels to the test instances (we only care about model predictions of ow evaluation) - ideally, num classes should be given in this case')
parser.add_argument("--num_classes", type=int, default=None, help="fixed num classes") # added this for my own ow evaluation

# Parse arguments
args = parser.parse_args()
dataset_path = "./datasets"
if args.compute_canada:
    dataset_path = '/home/kka151/scratch/holmes/datasets'



# Ensure the specified device is available
if args.device.startswith("cuda"):
    assert torch.cuda.is_available(), f"The specified device {args.device} does not exist"
device = torch.device(args.device)

# Define paths for dataset, logs, and checkpoints
in_path = os.path.join(dataset_path, args.dataset)
if not os.path.exists(in_path):
    raise FileNotFoundError(f"The dataset path does not exist: {in_path}")
log_path = os.path.join(args.log_path, args.dataset, args.model)
ckp_path = os.path.join(args.checkpoints, args.dataset, args.model)
os.makedirs(log_path, exist_ok=True)
out_file = os.path.join(log_path, f"{args.result_file}.json")

# Load training and validation data
print(f"loading test file: ", os.path.join(in_path, f"{args.test_file}.npz"))
valid_X, valid_y = data_processor.load_data(os.path.join(in_path, f"{args.valid_file}.npz"), args.feature, args.seq_len, args.num_tabs)
test_X, test_y = data_processor.load_data(os.path.join(in_path, f"{args.test_file}.npz"), args.feature, args.seq_len, args.num_tabs)

if args.num_classes is not None:
    num_classes = args.num_classes
    if args.random_labels:
        test_y = torch.randint(0, args.num_classes, test_y.shape)
    
else:
    num_classes = len(np.unique(test_y))
    if args.random_labels:
        test_y = torch.randint(0, args.num_classes, test_y.shape)
    if args.num_tabs == 1:
        num_classes = len(np.unique(test_y))
        assert num_classes == test_y.max() + 1, "Labels are not continuous" # Ensure labels are continuous
    else:
        num_classes = test_y.shape[1]

# Print dataset information
print(f"Valid: X={valid_X.shape}, y={valid_y.shape}")
print(f"Test: X={test_X.shape}, y={test_y.shape}")
print(f"num_classes: {num_classes}")

# Load data into iterators
valid_iter = data_processor.load_iter(valid_X, valid_y, args.batch_size, False, args.num_workers)
test_iter = data_processor.load_iter(test_X, test_y, args.batch_size, False, args.num_workers)

# Initialize model, optimizer, and loss function
if args.model in ["BAPM", "TMWF"]: # Assume num_tabs is known
    model = eval(f"models.{args.model}")(num_classes, args.num_tabs)
else:
    model = eval(f"models.{args.model}")(num_classes)

model.load_state_dict(torch.load(os.path.join(ckp_path, f"{args.load_name}.pth"), map_location="cpu"))
model.to(device)

# Evaluation
filename_predict = f"{args.test_file}_{args.eval_method}_predictions.npy"
filename_true = f"{args.test_file}_{args.eval_method}_true_labels.npy"
filename_logits = f"{args.test_file}_{args.eval_method}_logits.npy"
filename_probs = f"{args.test_file}_{args.eval_method}_probs.npy"
prediction_save_path = os.path.join(in_path, 'holmes_predictions')
model_utils.model_eval(
    model,
    test_iter,
    valid_iter,
    args.eval_method,
    args.eval_metrics, 
    out_file,
    num_classes,
    ckp_path,
    args.scenario,
    args.num_tabs,
    device,
    save_path= prediction_save_path,
    save_predictions= True,
    filename_predict = filename_predict,
    filename_true = filename_true,
    filename_logits= filename_logits,
    filename_prob= filename_probs
)