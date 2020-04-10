#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This script is for project2, which aims to perform the following tasks:
 * Resample these data when they are unbalanced
 * Scale the data
 * Fits ANN
 * exports the results in a zip file

example usage from CLI:
 $ python3 subtasks_ANN.py --train_features /path/to/preprocessed_train_features.csv
     --train_labels /path/to/preprocessed_train_labels.csv
     --test_features /path/to/preprocessed_test_features.csv
     --predictions /path/to/preprocessed_predictions_subtask3.zip
     --scaler minmax
     --model ANN
     --epochs 100

For help, run:
 $ subtasks_ANN.py -h

TODO:
    * Scale labels for sigmoid function for classifiers

Following Google style guide: http://google.github.io/styleguide/pyguide.html

"""

__author__ = "Josephine Yates; Philip Hartout"
__email__ = "jyates@student.ethz.ch; phartout@student.ethz.ch"

import multiprocessing
import argparse
import logging
import os
import shutil
import sys
import zipfile
import time

import torch
from imblearn.over_sampling import ADASYN, SMOTE
from imblearn.under_sampling import ClusterCentroids, RandomUnderSampler
import pandas as pd
import numpy as np
from tqdm import tqdm
from sklearn.svm import SVR
from sklearn.metrics import f1_score, mean_squared_error, accuracy_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from torch.utils.data import Dataset, DataLoader
from torch.utils.tensorboard import SummaryWriter

IDENTIFIERS = ["pid"]
MEDICAL_TESTS = [
    "LABEL_BaseExcess",
    "LABEL_Fibrinogen",
    "LABEL_AST",
    "LABEL_Alkalinephos",
    "LABEL_Bilirubin_total",
    "LABEL_Lactate",
    "LABEL_TroponinI",
    "LABEL_SaO2",
    "LABEL_Bilirubin_direct",
    "LABEL_EtCO2",
]
VITAL_SIGNS = ["LABEL_RRate", "LABEL_ABPm", "LABEL_SpO2", "LABEL_Heartrate"]
SEPSIS = ["LABEL_Sepsis"]


def load_data():
    """Loads the preprocessed data to three different dataframes.

    Returns:
        df_train, df_train_label, df_test (pandas.core.frame.DataFrame): three dataframes
        containing the
        preprocessed training features, training labels and testing features respectively.

    """
    df_train = pd.read_csv(FLAGS.train_features, nrows=FLAGS.nb_of_patients)
    df_train_label = pd.read_csv(FLAGS.train_labels, nrows=FLAGS.nb_of_patients)
    df_test = pd.read_csv(FLAGS.test_features)
    return df_train, df_train_label, df_test


def data_formatting(df_train, df_train_label, logger):
    """Function takes data in for formatting

    Args:
        df_train (pandas.core.DataFrame): preprocessed training features
        df_train_label (pandas.core.DataFrame): preprocessed training labels
        logger (Logger): logger

    Returns:
        X_train (np.ndarray): (n_samples, n_features) array containing features
        y_train_vital_signs (np.ndarray): (n_samples, n_features) array labels

        transform outputs later on when scaling back predictions for interpretability
    """

    # Cast to arrays
    X_train = df_train.drop(columns=IDENTIFIERS).values

    # Create list with different label for each medical test
    logger.info("Creating a list of labels for each medical test")
    y_train_medical_tests = []
    for test in MEDICAL_TESTS:
        y_train_medical_tests.append(df_train_label[test].astype(int).values)

    # Create list with different label for sepsis
    logger.info("Creating a list of labels for each medical test")
    y_train_sepsis = []
    for sepsis in SEPSIS:
        y_train_sepsis.append(df_train_label[sepsis].astype(int).values)

    # Create list with different label for each vital sign
    logger.info("Creating a list of labels for each vital sign")
    y_train_vital_signs = []
    for sign in VITAL_SIGNS:
        y_train_vital_signs.append(df_train_label[sign].astype(int).values)

    # Scale data to avoid convergence warning
    logger.info(f"Scaling data using {FLAGS.scaler}.")

    if FLAGS.scaler == "standard":
        scaler = StandardScaler(with_mean=True, with_std=True)
    else:
        scaler = MinMaxScaler()

    X_train = scaler.fit_transform(X_train)

    return X_train, y_train_medical_tests, y_train_sepsis, y_train_vital_signs


def oversampling_strategies(X_train, y_train, strategy):
    """Function that uses a strategy to balance the dataset.

    Args:
        X_train (numpy.ndarray): array containing the features that need to be balanced
        y_train (numpy.ndarray): array containing the data labels
        strategy (int): sampling strategy to be adopted

    Returns:
        X_train_resampled, y_train_resampled (numpy.ndarray): resampled features and labels
        according to the chosen strategy
    """

    # Oversampling methods
    if strategy == "adasyn":
        sampling_method = ADASYN()
    if strategy == "smote":
        sampling_method = SMOTE()

    # Undersampling methods
    if strategy == "clustercentroids":
        sampling_method = ClusterCentroids(random_state=42)
    if strategy == "random":
        sampling_method = RandomUnderSampler(random_state=0, replacement=True)

    X_train_resampled, y_train_resampled = sampling_method.fit_sample(X_train, y_train)

    return X_train_resampled, y_train_resampled


def convert_to_cuda_tensor(X_train, X_test, y_train, y_test, device):
    """Converts a number of np.ndarrays to tensors placed on the device specified.

    Args:
        X_train (np.ndarray): (n_samples, n_features) array containing training features
        X_test (np.ndarray): (n_samples, n_features) array containing testing features
        y_train (np.ndarray): (n_samples,) array containing training labels
        y_test (np.ndarray): (n_samples,) array containing testing labels
        device (torch.device): device on which the tensors should be placed (CPU/CUDA GPU)

    Returns:

    """
    return (
        torch.from_numpy(X_train).to(device).float(),
        torch.from_numpy(X_test).to(device).float(),
        torch.from_numpy(y_train).to(device).float(),
        torch.from_numpy(y_test).to(device).float(),
    )


class Feedforward(torch.nn.Module):
    """ Definition of the feedfoward neural network. It currently has three layers which can be
    modified in the function where the network is trained.
    """

    def __init__(self, input_size, hidden_size, subtask, p=0.2):
        super(Feedforward, self).__init__()
        self.subtask = subtask
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.dropout = torch.nn.Dropout(p=p)
        self.bn = torch.nn.BatchNorm1d(hidden_size)
        self.relu = torch.nn.ReLU()
        self.sigmoid = torch.nn.Sigmoid()
        self.fc1 = torch.nn.Linear(self.input_size, self.hidden_size)
        torch.nn.init.xavier_normal_(self.fc1.weight)
        self.fc2 = torch.nn.Linear(self.hidden_size, hidden_size)
        torch.nn.init.xavier_normal_(self.fc2.weight)
        self.fc3 = torch.nn.Linear(self.hidden_size, hidden_size)
        torch.nn.init.xavier_normal_(self.fc3.weight)
        self.fc4 = torch.nn.Linear(self.hidden_size, 1)
        torch.nn.init.xavier_normal_(self.fc4.weight)

    def forward(self, x):
        """Function where the forward pass is defined. The backward pass is deternmined by the
            autograd function built into PyTorch.

        Args:
            x (torch.Tensor): Tensor (n_samples,n_features) tensor containing training input
                features
            subtask (int): subtask performed (choice: 1,2,3)

        Returns:
            output (torch.Tensor): (n_samples,n_features) tensor containing
                the predicted output for each sample.
        """
        assert self.subtask in [1, 2, 3]
        hidden = self.fc1(x)
        hidden_bn = self.bn(hidden)
        relu = self.relu(hidden_bn)
        hidden_2 = self.dropout(self.fc2(relu))
        hidden_2_bn = self.bn(hidden_2)
        relu_2 = self.relu(hidden_2_bn)
        hidden_3 = self.dropout(self.fc3(relu))
        hidden_3_bn = self.bn(hidden_3)
        relu_3 = self.relu(hidden_3_bn)
        output = self.fc4(relu_3)
        if self.subtask == 1 or self.subtask == 2:
            output = self.sigmoid(output)
        else:
            output = self.relu(output)
        return output


class Data(Dataset):
    """ Class used to load the data in minibatches to control the neural network stability during
        training.
    """

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.len = self.x.shape[0]

    def __getitem__(self, index):
        return self.x[index], self.y[index]

    def __len__(self):
        return self.len


def get_ann_models(x_input, y_input, subtask, logger, device):
    """Main function to train the neural networks for the data.

    Args:
        x_input (np.ndarray): (n_samples,n_features) array containing the training features
        y_input (np.ndarray): (n_samples,) array containing the training labels
        subtask (int): subtask to be performed (choice: 1, 2, 3)
        logger (Logger): logger
        device (torch.device): device on which the tensors should be placed (CPU/CUDA GPU)

    Returns:
        ann_models (list): list of trained feedforward neural networks
        scores (list): list of the testing scores of the trained feedforward neural networks
    """
    assert subtask in [1, 2, 3]
    logger.info(
        "Using {} to train the neural network for substask {}.".format(device, subtask)
    )
    ann_models = []
    scores = []
    topred = (
        MEDICAL_TESTS if subtask == 1 else (SEPSIS if subtask == 2 else VITAL_SIGNS)
    )
    for i, sign in enumerate(topred):
        logger.info(f"Starting neural network training for {sign}")
        X_train, X_test, y_train, y_test = train_test_split(
            x_input, y_input[i], test_size=0.10, random_state=42, shuffle=True
        )
        if subtask in [1, 2]:
            logger.info(
                "Performing {} strategy for oversampling for {}".format(
                    FLAGS.sampling_strategy, sign
                )
            )
            X_train, y_train = oversampling_strategies(
                X_train, y_train, FLAGS.sampling_strategy
            )
        logger.info("Converting arrays to tensors")
        X_train_tensor, X_test_tensor, y_train_tensor, y_test_tensor = convert_to_cuda_tensor(
            X_train, X_test, y_train, y_test, device
        )
        model = Feedforward(X_train_tensor.shape[1], 150, subtask, 0.5)
        if subtask == 3:
            criterion = torch.nn.MSELoss()
        else:
            criterion = torch.nn.BCELoss()
        # optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
        dataset = Data(X_train_tensor, y_train_tensor)
        batch_size = 2048  # Ideally we want any multiple of 12 here
        trainloader = DataLoader(dataset=dataset, batch_size=batch_size)

        if torch.cuda.is_available():
            model.cuda()
        model.float()

        logger.info("Removing data from previous run if there was any.")
        dirpath = os.path.join(os.getcwd(), "runs")
        fileList = os.listdir(dirpath)
        for fileName in fileList:
            shutil.rmtree(dirpath + "/" + fileName)

        logger.info("Commencing neural network training.")
        now = time.strftime("%Y%m%d-%H%M%S")
        writer = SummaryWriter(
            log_dir=f"runs/ann_network_runs_{FLAGS.epochs}_epochs_{now}"
        )
        for epoch in tqdm(list(range(FLAGS.epochs))):
            LOSS = []
            for x, y in trainloader:
                yhat = model(x)
                loss = criterion(yhat.float(), y.reshape((y.shape[0], 1)))
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                LOSS.append(loss)
            X_test_tensor = X_test_tensor.to(device)
            y_test_pred = model(X_test_tensor).cpu().detach().numpy()
            y_train_pred = model(X_train_tensor).cpu().detach().numpy()
            loss_average = sum(LOSS) / len(LOSS)
            writer.add_scalar("Training_loss", loss_average, epoch)

            if subtask in [1, 2]:
                # can change decision boundary (0.5 is equivalent to rounding)
                db = np.vectorize(lambda x: (0 if x < 0.5 else 1))
                y_test_pred_bin = db(y_test_pred)
                y_train_pred_bin = db(y_train_pred)
                train_acc = accuracy_score(y_train_pred_bin, y_train)
                test_acc = accuracy_score(y_test_pred_bin, y_test)
                f1_score_train = f1_score(y_train, y_train_pred_bin)
                f1_score_test = f1_score(y_test, y_test_pred_bin)
                writer.add_scalar("Training_acc", train_acc, epoch)
                writer.add_scalar("Testing_acc", test_acc, epoch)
                writer.add_scalar("Training_f1", f1_score_train, epoch)
                writer.add_scalar("Testing_f1", f1_score_test, epoch)
            if subtask == 3:
                mse_score_train = mean_squared_error(y_train, y_train_pred)
                mse_score_test = mean_squared_error(y_test, y_test_pred)
                writer.add_scalar("Training_mse", mse_score_train, epoch)
                writer.add_scalar("Testing_mse", mse_score_test, epoch)

        writer.close()

        logger.info(
            f"Value of the test sample is {y_test} and value for the predicted "
            f"sample is {y_test_pred}"
        )
        logger.info(f"Finished test for {sign}")
        ann_models.append(model)
        scores.append(LOSS)
    return ann_models, scores


def get_predictions(X_test, test_pids, models, subtask, device):
    """Function to obtain predictions for every model, as a confidence level for subtask 1 and 2
    (the closer to 1 (resp 0), the more confidently the sample belongs to class 1 (resp 0)) or as 
    a value prediction for subtask 3

    Args:
        X_test (np.ndarray): array of preprocessed test values
        test_pids (np.ndarray): array of patient ids in test set
        models (list): list of models for each of the medical tests
        subtask (int): subtask to be performed (choice: 1, 2, 3)
        device (torch.device): device on which the tensors should be placed (CPU/CUDA GPU)

    Returns:
        df_pred (pandas.core.DataFrame): contains the predictions made by each of the models for
            their respective tests, containing for each patient id the predicted label as a
            confidence level.
    """
    df_pred = pd.DataFrame(index=test_pids)

    topred = (
        MEDICAL_TESTS if subtask == 1 else (SEPSIS if subtask == 2 else VITAL_SIGNS)
    )
    for i, test in enumerate(topred):
        # Switch network to eval mode to make sure all dropout layers are there, etc..
        y_pred = (
            models[i](torch.from_numpy(X_test).to(device).float())
            .cpu()
            .detach()
            .numpy()
        )
        df = pd.DataFrame(y_pred, index=test_pids, columns=[topred[i]])
        df_pred = df_pred.merge(df, left_index=True, right_index=True)
    df_pred = df_pred.reset_index().rename(columns={"index": "pid"})
    return df_pred


def main(logger):
    """Primary function reading, preprocessing and modelling the data

    Args:
        logger (Logger): logger to get information about the status of the script when running

    Returns:
        None
    """

    logger.info("Loading data")
    df_train, df_train_label, df_test = load_data()
    logger.info("Finished Loading data")

    X_train, y_train_medical_tests, y_train_sepsis, y_train_vital_signs = data_formatting(
        df_train, df_train_label, logger
    )

    logger.info("Beginning modelling process.")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    # get models and scores for substasks 1, 2 and 3
    logger.info("Beggining ANN training for medical tests.")
    medical_tests_models, scores = get_ann_models(
        X_train, y_train_medical_tests, 1, logger, device
    )

    logger.info("Beggining ANN training for sepsis.")
    sepsis_models, scores = get_ann_models(X_train, y_train_sepsis, 2, logger, device)

    logger.info("Beggining ANN training for vital signs.")
    vital_signs_models, scores = get_ann_models(
        X_train, y_train_vital_signs, 3, logger, device
    )

    # get the unique test ids of patients
    test_pids = np.unique(df_test["pid"].values)
    logger.info("Fetch predictions.")
    X_test = df_test.drop(columns=IDENTIFIERS).values

    # get the predictions for all subtasks
    logger.info("Get predictions for medical tests.")
    medical_tests_predictions = get_predictions(
        X_test, test_pids, medical_tests_models, 1, device
    )

    logger.info("Get predictions for sepsis.")
    sepsis_predictions = get_predictions(X_test, test_pids, sepsis_models, 2, device)

    logger.info("Get predictions for vital signs.")
    vital_signs_predictions = get_predictions(
        X_test, test_pids, vital_signs_models, 3, device
    )
    df_predictions = pd.DataFrame(test_pids, columns=["pid"])
    df_predictions = df_predictions.merge(
        medical_tests_predictions, left_on="pid", right_on="pid"
    )
    df_predictions = df_predictions.merge(
        sepsis_predictions, left_on="pid", right_on="pid"
    )
    df_predictions = df_predictions.merge(
        vital_signs_predictions, left_on="pid", right_on="pid"
    )
    logger.info("Export predictions DataFrame to a zip file")
    # # Export pandas dataframe to zip archive.
    # df_predictions.to_csv(
    #     FLAGS.predictions, index=False, float_format="%.3f", compression=dict(method='zip',
    #                     archive_name='predictions.csv')
    # )
    # Alternative way to export to CSV that works.
    df_predictions.to_csv(
        "predictions.csv",
        index=None,
        sep=",",
        header=True,
        encoding="utf-8-sig",
        float_format="%.2f",
    )

    with zipfile.ZipFile("predictions.zip", "w") as zf:
        zf.write("predictions.csv")
    os.remove("predictions.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CLI args for folder and file \
    directories as well as model options"
    )

    parser.add_argument(
        "--train_features",
        "-train_f",
        type=str,
        required=True,
        help="path to the CSV file containing the preprocessed training \
      features",
    )

    parser.add_argument(
        "--test_features",
        "-test",
        type=str,
        required=True,
        help="path to the CSV file containing the preprocessed testing \
 features",
    )

    parser.add_argument(
        "--train_labels",
        "-train_l",
        type=str,
        required=True,
        help="path to the CSV file containing the preprocessed training \
     labels",
    )

    parser.add_argument(
        "--predictions",
        "-pred",
        type=str,
        required=True,
        help="path to the zip file containing the \
     predictions",
    )

    parser.add_argument(
        "--nb_of_patients",
        "-nb_pat",
        type=int,
        required=False,
        help="Number of patients to consider in run. If not specified, then consider all patients",
    )

    parser.add_argument(
        "--scaler",
        "-scale",
        type=str,
        required=True,
        help="Scaler to be used to transform the data.",
        choices=["minmax", "standard"],
    )

    parser.add_argument(
        "--epochs", "-ep", type=int, required=False, help="", default=100
    )

    parser.add_argument(
        "--sampling_strategy",
        "-samp",
        type=str,
        required=True,
        help="Sampling strategy to adopt to overcome the imbalanced dataset problem"
        "any of adasyn, smote, clustercentroids or random.",
        choices=["adasyn", "smote", "clustercentroids", "random"],
    )

    FLAGS = parser.parse_args()

    # clear logger.
    logging.basicConfig(level=logging.DEBUG, filename="log_subtasks_ANN.log")

    logger = logging.getLogger("IML-P2-T123-ANN")

    # Create a second stream handler for logging to `stderr`, but set
    # its log level to be a little bit smaller such that we only have
    # informative messages
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)

    # Use the default format; since we do not adjust the logger before,
    # this is all right.
    stream_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s"
        )
    )
    logger.addHandler(stream_handler)

    logger.info("Usage:\n{0}\n".format(" ".join([x for x in sys.argv])))
    logger.info("All settings used:")
    for k, v in sorted(vars(FLAGS).items()):
        logger.info("{0}: {1}".format(k, v))

    main(logger)
