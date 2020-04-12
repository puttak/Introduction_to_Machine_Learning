#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to preprocess the dataset and export it for other modelling scripts

example usage from CLI:
 $ python3 data_preprocessing.py --train_features TRAIN_FEATURES
                             --test_features TEST_FEATURES
                             --train_labels TRAIN_LABELS
                             --preprocess_train PREPROCESS_TRAIN
                             --preprocess_test PREPROCESS_TEST
                             --preprocess_train_label PREPROCESS_TRAIN_LABEL
                             [--nb_of_patients NB_OF_PATIENTS]

For help, run:
 $ python data_preprocessing.py -h


Following Google style guide: http://google.github.io/styleguide/pyguide.html

"""


import argparse
import logging

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression, BayesianRidge
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
from tqdm import tqdm

TYPICAL_VALUES = {
    "pid": 15788.831218741774,
    "Time": 7.014398525927875,
    "Age": 62.07380889707818,
    "EtCO2": 32.88311356434632,
    "PTT": 40.09130983590656,
    "BUN": 23.192663516538175,
    "Lactate": 2.8597155076236422,
    "Temp": 36.852135856500034,
    "Hgb": 10.628207669881103,
    "HCO3": 23.488100167210746,
    "BaseExcess": -1.2392844571830848,
    "RRate": 18.154043187688046,
    "Fibrinogen": 262.496911351785,
    "Phosphate": 3.612519413287318,
    "WBC": 11.738648535345682,
    "Creatinine": 1.4957773156474896,
    "PaCO2": 41.11569643111729,
    "AST": 193.4448880402708,
    "FiO2": 0.7016656642357807,
    "Platelets": 204.66642639312448,
    "SaO2": 93.010527124635,
    "Glucose": 142.169406624713,
    "ABPm": 82.11727559995713,
    "Magnesium": 2.004148832962384,
    "Potassium": 4.152729193815373,
    "ABPd": 64.01471072970384,
    "Calcium": 7.161149186763874,
    "Alkalinephos": 97.79616327960757,
    "SpO2": 97.6634493216935,
    "Bilirubin_direct": 1.390723226703758,
    "Chloride": 106.26018538478121,
    "Hct": 31.28308971681893,
    "Heartrate": 84.52237068276303,
    "Bilirubin_total": 1.6409406684190786,
    "TroponinI": 7.269239936440605,
    "ABPs": 122.3698773806418,
    "pH": 7.367231494050988,
}

IDENTIFIERS = ["pid", "Time"]
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
ESTIMATOR = {"bayesian": BayesianRidge(), "decisiontree": DecisionTreeRegressor(max_features="sqrt", random_state=0), 
                "extratree": ExtraTreesRegressor(n_estimators=10, random_state=0), 
                "knn": KNeighborsRegressor(n_neighbors=10, weights="distance")}

def load_data():
    """Loads data to three different dataframes.

    Returns:
        df_train, df_train_label, df_test (pandas.core.frame.DataFrame): three dataframes containing
        the training features, training labels and testing features respectively.

    """
    if FLAGS.nb_of_patients is not None:
        rows_to_load = FLAGS.nb_of_patients * 12
    else:
        rows_to_load = None
    df_train = pd.read_csv(FLAGS.train_features, nrows=rows_to_load, float_precision="%.3f")
    df_train_label = pd.read_csv(FLAGS.train_labels, nrows=rows_to_load)
    df_test = pd.read_csv(FLAGS.test_features, nrows=rows_to_load, float_precision="%.3f")
    return df_train, df_train_label, df_test


# slower version - supports patient specific mean/median
def fill_na_with_average_patient_column(df, logger):
    """Fills NaNs with the average value of each column for each patient if available,
    otherwise column-wide entry

    Args:
        df (pandas.core.frame.DataFrame): data to be transformed
        logger (Logger): logger

    Returns:
        df (pandas.core.frame.DataFrame): dataframe containing the transformed data
    """
    columns = list(df.columns)
    for i, column in tqdm(enumerate(columns)):
        # Fill na with patient average
        df[[column]] = df.groupby(["pid"])[column].transform(
            lambda x: x.fillna(x.median())
        )

    # Fill na with overall column average for lack of a better option for now
    df = df.fillna(df.median())
    if df.isnull().values.any():
        columns_with_na = df.columns[df.isna().any()].tolist()
        for column in columns_with_na:
            df[column] = TYPICAL_VALUES[column]
    return df


def missing_data_imputer_modelling(df_train, imputation_type, logger):
    """Basically the same as missing_data_imputer() but using the sklearn API.

    Args:
        df_train (pandas.core.frame.DataFrame): dataframe with training data
        imputation_type (string): the type of imputation to perform, choice in \
            ["bayesian","decisiontree","extratree","knn"]
        logger (Logger): logger

    Returns: df_train_preprocessed (pandas.core.frame.DataFrame): dataframe with imputed data

    """
    logger.info("Creating missing data dataframe")
    assert(imputation_type in ["bayesian","decisiontree","extratree","knn"]), \
        "imputation type must be in [bayesian, decisiontree ,extratree, knn]"
    pid = df_train["pid"].unique()
    columns = df_train.columns
    df_train_preprocessed = pd.DataFrame(columns=columns, index=pid)
    estimator = ESTIMATOR[imputation_type]
    samp_post = (True if imputation_type=="bayesian" else False)
    imp_mean = IterativeImputer(
        estimator=estimator,
        missing_values=np.nan,
        sample_posterior=samp_post,
        max_iter=10,
        tol=0.001,
        n_nearest_features=None, # Meaning all features are used
        initial_strategy='median',
        imputation_order='descending',
        skip_complete=False,
        min_value=None,
        max_value=None,
        verbose=2,
        random_state=42,
        add_indicator=False
    )
    columns = df_train.columns
    logger.info("Commencing data imputation process")
    df_train = imp_mean.fit_transform(df_train.values)
    df_train = pd.DataFrame(df_train, columns=columns)
    logger.info("Take mean over patients")
    for patient in tqdm(pid):
        for column in df_train.columns:
            df_train_preprocessed.at[patient, column] = df_train.loc[
                df_train["pid"] == patient
            ][column].mean()

    return df_train_preprocessed


def visualize_data(X):
    plt.rcParams['figure.figsize'] = 20, 5
    cols_to_plot = []
    for column in range(X.shape[1]):
        cols_to_plot.append(column)
        if len(cols_to_plot) % 10 == 0 and len(cols_to_plot) != 0:
            plot = sns.violinplot(data=X[:, min(cols_to_plot):column])
            # plot.set(yscale="log")
            plt.show()
            cols_to_plot = []


def missing_data_imputer(df_train, logger):
    """Imputes data and returns a dataframe with one row per patient filled with the values as
    follows:
        * If the amount of data that is there is above 8, then fit a linear regression and
            take the coefficient as input
        * If the amount of data that is there is below 8, take the average
        * If no data is present fill the data with the column average or a typical value if no
            values is present in the case that a restricted number of patients are loaded.


    Args:
        df_train (pandas.core.Dataframe): input dataframe with the features that need to be
            augmented.
        logger (Logger): logger.

    Returns:
        pandas.core.DataFrame

    """

    logger.info("Creating missing data dataframe")
    pid = df_train["pid"].unique()
    df_na = pd.DataFrame(columns=df_train.columns)
    processed_df_columns = [x for x in df_train.columns if x not in IDENTIFIERS]
    df_train_preprocessed = pd.DataFrame(columns=processed_df_columns, index=pid)
    for patient in tqdm(pid):
        df_na = df_na.append(
            df_train.loc[df_train["pid"] == patient].isna().sum(), ignore_index=True
        )

    logger.info("Getting quantile information")
    column_quantiles = {}
    columns = df_na.columns.tolist()
    columns = [x for x in columns if x not in IDENTIFIERS]
    for column in tqdm(columns):
        column_quantiles[column] = df_na[column].quantile(0.25)

    columns_for_regression = [k for k, v in column_quantiles.items() if float(v) <= 8]
    columns_for_regression.remove("Age")
    columns_for_averaging = np.setdiff1d(
        np.array(df_train.columns), np.array(columns_for_regression)
    ).tolist()
    columns_for_regression_formatted = [
        sub + "_trend" for sub in columns_for_regression
    ]
    columns_for_averaging = [x for x in columns_for_averaging if x not in IDENTIFIERS]
    df_train_preprocessed = df_train_preprocessed.reindex(
        df_train_preprocessed.columns.tolist() + columns_for_regression_formatted,
        axis=1,
    )

    logger.info("Commencing data imputation process")
    logger.info(f"Add trends for: {columns_for_regression}")
    for patient in tqdm(pid):
        for column in columns_for_regression:
            if df_train.loc[df_train["pid"] == patient][column].isna().sum() <= 8:
                series = df_train.loc[df_train["pid"] == patient][column]
                # Fill missing values between two non nans with their average
                series = (series.ffill() + series.bfill()) / 2
                # Drop the rest of the value
                series = series.dropna()
                X = [i for i in range(0, len(series))]
                X = np.reshape(X, (len(X), 1))
                y = series
                model = LinearRegression()
                model.fit(X, y)
                df_train_preprocessed.at[patient, column + "_trend"] = model.coef_

    # fill rest of values with 0 for trends col umns
    df_train_preprocessed[columns_for_regression_formatted] = df_train_preprocessed[
        columns_for_regression_formatted
    ].fillna(value=0)

    # Where it is not reasonable to fit a line, we can still take the average of all available
    # values and use that as feature
    logger.info(
        "Imputing values for columns where there is not enough information for trends"
        " but enough to make an average for each patient."
    )
    for patient in tqdm(pid):
        for column in columns_for_averaging:
            df_train_preprocessed.at[patient, column] = df_train.loc[
                df_train["pid"] == patient
            ][column].median()

    logger.info(
        "Imputing for the remaining columns where no specific patient average can be found"
    )
    # Fill na with overall column average for lack of a better option for now
    df_train_preprocessed = df_train_preprocessed.fillna(df_train_preprocessed.median())
    # This is only when testing where there is not always data for all loaded rows.
    if df_train_preprocessed.isnull().values.any():
        columns_with_na = df_train_preprocessed.columns[
            df_train_preprocessed.isna().any()
        ].tolist()
        for column in columns_with_na:
            df_train_preprocessed[column] = TYPICAL_VALUES[column]

    df_train_preprocessed = df_train_preprocessed.reset_index()
    df_train_preprocessed = df_train_preprocessed.rename(columns={"index": "pid"})
    return df_train_preprocessed


def main(logger):
    """Primary function reading and preprocessing the data

    Args:
        logger (Logger): logger to get information about the status of the script when running

    Returns:
        None
    """

    logger.info("Loading data")
    df_train, df_train_label, df_test = load_data()
    logger.info("Finished Loading data")
    logger.info("Imputing technique used is {}".format(FLAGS.data_imputer))
    logger.info("Preprocessing training set")
    # Would be useful to distribute/multithread this part
    # df_train_preprocessed = fill_na_with_average_patient_column(
    #     df_train, logger
    # )

    if FLAGS.data_imputer == "manual":
        df_train_preprocessed = missing_data_imputer(df_train, logger)
    else:
        df_train_preprocessed = missing_data_imputer_modelling(df_train, FLAGS.data_imputer, logger)

    # Cast training labels for these tasks
    df_train_label[MEDICAL_TESTS + VITAL_SIGNS + SEPSIS] = df_train_label[
        MEDICAL_TESTS + VITAL_SIGNS + SEPSIS
    ].astype(int)

    # Merging pids to make sure they map correctly and we did not mess up our preprocessing.
    df_train_preprocessed_merged = pd.merge(
        df_train_preprocessed, df_train_label, how="left", left_on="pid", right_on="pid"
    )

    df_train_label_preprocessed = df_train_preprocessed_merged[
        ["pid"] + MEDICAL_TESTS + VITAL_SIGNS + SEPSIS
    ]
    logger.info("Preprocessing test set")
    if FLAGS.data_imputer == "manual":
        df_test_preprocessed = missing_data_imputer(df_test, logger)
    else:
        df_test_preprocessed = missing_data_imputer_modelling(df_test, FLAGS.data_imputer, logger)


    logger.info("Export preprocessed train and test set")
    # Export pandas dataframe to csv.
    df_train_label_preprocessed.to_csv(
        FLAGS.preprocess_train_label, index=False, float_format="%.3f"
    )
    df_train_preprocessed.to_csv(
        FLAGS.preprocess_train, index=False, float_format="%.3f"
    )
    df_test_preprocessed.to_csv(FLAGS.preprocess_test, index=False, float_format="%.3f")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CLI args for folder and file \
    directories"
    )

    parser.add_argument(
        "--train_features",
        "-train_f",
        type=str,
        required=True,
        help="path to the CSV file containing the training \
                        features",
    )

    parser.add_argument(
        "--test_features",
        "-test",
        type=str,
        required=True,
        help="path to the CSV file containing the testing \
                            features",
    )

    parser.add_argument(
        "--train_labels",
        "-train_l",
        type=str,
        required=True,
        help="path to the CSV file containing the training \
                                labels",
    )

    parser.add_argument(
        "--preprocess_train",
        "-pre_train",
        type=str,
        required=True,
        help="path to the CSV file containing the training \
                                 preprocessed data",
    )

    parser.add_argument(
        "--preprocess_test",
        "-pre_test",
        type=str,
        required=True,
        help="path to the CSV file containing the test \
                                preprocessed data",
    )

    parser.add_argument(
        "--preprocess_train_label",
        "-pre_label",
        type=str,
        required=True,
        help="path to the CSV file containing the training \
                                label data",
    )

    parser.add_argument(
        "--data_imputer",
        "-imputer",
        type=str,
        required=True,
        choices=["manual","bayesian","decisiontree","extratree","knn"],
        help="Data imputer.",
    )

    parser.add_argument(
        "--nb_of_patients",
        "-b_path",
        type=int,
        required=False,
        help="number of patients to load",
    )

    FLAGS = parser.parse_args()

    # clear logger.
    logging.basicConfig(level=logging.DEBUG, filename="script_status_subtask1and2.log")

    logger = logging.getLogger("Data preprocessing")

    # Create a second stream handler for logging to `stderr`, but set
    # its log level to be a little bit smaller such that we only have
    # informative messages
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)

    # Use the default format; since we do not adjust the logger before,
    # this is all right.
    stream_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] "
            "%(message)s"
        )
    )
    logger.addHandler(stream_handler)

    main(logger)
