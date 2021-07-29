from tagset_maps import swum_pos_dictionary, posse_pos_dictionary, stanford_pos_dictionary
import logging
root_logger = logging.getLogger(__name__)
root_logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('tagger_error.log', 'a', 'utf-8')
root_logger.addHandler(handler)
import sqlite3
import sys
import joblib
import pandas as pd
import subprocess
import re
from spiral import ronin
from enum import IntEnum
import pexpect

stanford_process = pexpect.spawn("java -mx3g -cp '../stanford-postagger-2018-10-16/stanford-postagger.jar:' edu.stanford.nlp.tagger.maxent.MaxentTagger -model ../stanford-postagger-2018-10-16/models/english-bidirectional-distsim.tagger")
stanford_process.expect("(For EOF, use Return, Ctrl-D on Unix; Enter, Ctrl-Z, Enter on Windows.)")

class CODE_CONTEXT(IntEnum):
    ATTRIBUTE = 1
    CLASS = 2
    DECLARATION = 3
    FUNCTION = 4
    PARAMETER = 5

def get_identifier_context(id_type):
   IDENTIFIER_TYPE = {}
   IDENTIFIER_TYPE['ATTRIBUTE'] = CODE_CONTEXT.ATTRIBUTE
   IDENTIFIER_TYPE['CLASS'] = CODE_CONTEXT.CLASS
   IDENTIFIER_TYPE['DECLARATION'] = CODE_CONTEXT.DECLARATION
   IDENTIFIER_TYPE['FUNCTION'] = CODE_CONTEXT.FUNCTION
   IDENTIFIER_TYPE['PARAMETER'] = CODE_CONTEXT.PARAMETER
   if id_type in IDENTIFIER_TYPE:
        return IDENTIFIER_TYPE[id_type]
   else:
        raise Exception("CONTEXT {context} NOT FOUND".format(context=id_type))

def split_raw_identifier(identifier_data):
    if '(' in identifier_data: 
        identifier_data = identifier_data.split('(')[0]
    identifier_type_and_name = identifier_data.split()
    if len(identifier_type_and_name) < 2: 
        raise Exception("Malformed identifier")
    return identifier_type_and_name
def calculate_normalized_length(ensemble_input):
    i = 0
    for key, value in ensemble_input.items():
        if i == 0:
            ensemble_input[key].append(0)
        elif i > 0 and i < (len(ensemble_input)-1):
            ensemble_input[key].append(1)
        else:
            ensemble_input[key].append(2)
        i = i + 1
    return ensemble_input

def add_code_context(ensemble_input, context):
    for key, value in ensemble_input.items():
        try:
            ensemble_input[key].append(get_identifier_context(context))
        except Exception as context_exception:
            raise context_exception
    return ensemble_input

def ParseSwum(swum_output, split_identifier_name):
    code_context = swum_output.split('#')
    raw_grammar_pattern = grammar_pattern = identifier = []
    if code_context[0] == 'FIELD':
        identifier = code_context[1].split('-')[1].split()
        raw_grammar_pattern = re.findall('([A-Z]+)', ' '.join(identifier))
    else:
        identifier = code_context[1].split('@')[1].split('|')
        raw_grammar_pattern = re.findall('([A-Z]+)', ' '.join(identifier))
    
    for pos in raw_grammar_pattern:
        if pos in swum_pos_dictionary:
            grammar_pattern.append(swum_pos_dictionary[pos])

    #Sanity check: Identifier name can't be longer than grammar pattern
    if len(split_identifier_name) != len(grammar_pattern):
        root_logger.debug("SWUM: {taggerout} {ident}".format(taggerout=swum_output, ident=split_identifier_name))
        return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(["FAILURE" for x in split_identifier_name])))
        #raise Exception("Mismatch between name ({idname}) and grammar pattern ({gp})".format(idname=split_identifier_name, gp=grammar_pattern))

    return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(grammar_pattern)))
    
    return swum_output

def ParsePosse(posse_output, split_identifier_name):
    grammar_pattern = []
    raw_grammar_pattern = re.findall(':([A-Z-a-z]+)', posse_output)
    for pos_token in raw_grammar_pattern:
        if pos_token in posse_pos_dictionary:
            grammar_pattern.append(posse_pos_dictionary[pos_token])
        else:
            grammar_pattern.append(pos_token)
    
    #Sanity check: Identifier name can't be longer than grammar pattern
    if len(split_identifier_name) != len(grammar_pattern):
        root_logger.debug("POSSE: {taggerout} {ident}".format(taggerout=posse_output, ident=split_identifier_name))
        return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(["FAILURE" for x in split_identifier_name])))
    
    return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(grammar_pattern)))

def ParseStanford(stanford_output, split_identifier_name):
    grammar_pattern = []
    
    #We append 'I' to function names for Stanford. Remove it here.
    if stanford_output[0] == 'I' and not split_identifier_name[0] == 'I':
        stanford_output = ' '.join(stanford_output.split()[1:])

    raw_grammar_pattern = re.findall("_([A-Za-z]+)", stanford_output)
    for pos_token in raw_grammar_pattern:
        if pos_token in stanford_pos_dictionary:
            grammar_pattern.append(stanford_pos_dictionary[pos_token])
        else:
            grammar_pattern.append(pos_token)

    #Sanity check: Identifier name can't be longer than grammar pattern
    if len(split_identifier_name) != len(grammar_pattern):
        root_logger.debug("Stanford: {taggerout} {ident}".format(taggerout=stanford_output, ident=split_identifier_name))
        return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(["FAILURE" for x in split_identifier_name])))
    
    return("{identifier_names},{grammar_pattern}"
          .format(identifier_names=' '.join(split_identifier_name), 
            grammar_pattern=' '.join(grammar_pattern)))



def process_identifier_with_swum(identifier_data, context_of_identifier):
    #format identifier string in preparation to send it to SWUM
    identifier_type_and_name = split_raw_identifier(identifier_data)
    split_identifier_name_raw = ronin.split(identifier_type_and_name[1])
    split_identifier_name = '_'.join(ronin.split(identifier_type_and_name[1]))
    if get_identifier_context(context_of_identifier) != CODE_CONTEXT.FUNCTION:
        swum_string = "{identifier_type} {identifier_name}".format(identifier_name = split_identifier_name, identifier_type = identifier_type_and_name[0])
        swum_process = subprocess.Popen(['java', '-jar', '../SWUM/SWUM_POS/swum.jar', swum_string, '2', 'true'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        split_identifier_name = split_identifier_name+'('+identifier_data.split('(')[1]
        swum_string = " {identifier_type} {identifier_name}".format(identifier_name = split_identifier_name, identifier_type = identifier_type_and_name[0])
        swum_process = subprocess.Popen(['java', '-jar', '../SWUM/SWUM_POS/swum.jar', swum_string, '1', 'true'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    swum_out, swum_err = swum_process.communicate()
    swum_parsed_out = ParseSwum(swum_out.decode('utf-8').strip(), split_identifier_name_raw)
    return swum_parsed_out

def process_identifier_with_posse(identifier_data, context_of_identifier):
    #format identifier string in preparation to send it to POSSE
    identifier_type_and_name = split_raw_identifier(identifier_data)
    split_identifier_name_raw = ronin.split(identifier_type_and_name[1])
    split_identifier_name = ' '.join(split_identifier_name_raw)
    posse_string = "{data} | {identifier_name}".format(data = identifier_data, identifier_name = split_identifier_name)
    type_value = get_identifier_context(context_of_identifier)
    if any([type_value == x for x in [CODE_CONTEXT.DECLARATION, CODE_CONTEXT.ATTRIBUTE, CODE_CONTEXT.PARAMETER]]):
        posse_process = subprocess.Popen(['../POSSE/Scripts/mainParser.pl', 'A', posse_string], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elif type_value == CODE_CONTEXT.CLASS:
        posse_process = subprocess.Popen(['../POSSE/Scripts/mainParser.pl', 'C', posse_string], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        posse_process = subprocess.Popen(['../POSSE/Scripts/mainParser.pl', 'M', posse_string], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    posse_out, posse_err = posse_process.communicate()
    posse_out_parsed = ParsePosse(posse_out.decode('utf-8').strip(), split_identifier_name_raw)
    return posse_out_parsed

def process_identifier_with_stanford(identifier_data, context_of_identifier):
    identifier_type_and_name = identifier_data.split()
    identifier_type_and_name = split_raw_identifier(identifier_data)
    split_identifier_name_raw = ronin.split(identifier_type_and_name[1])
    if get_identifier_context(context_of_identifier) != CODE_CONTEXT.FUNCTION:
        split_identifier_name = "{identifier_name}".format(identifier_name=' '.join(split_identifier_name_raw))
    else:
        split_identifier_name = "I {identifier_name}".format(identifier_name=' '.join(split_identifier_name_raw))
    
    stanford_process.sendline(split_identifier_name)
    stanford_process.expect(' '.join([word+'_[A-Z]+' for word in split_identifier_name_raw]))
    #stanford_out, stanford_err = stanford_process.communicate()
    stanford_out = ParseStanford(stanford_process.after.decode('utf-8').strip(), split_identifier_name_raw)
    return stanford_out

def generate_ensemble_tagger_input_format(external_tagger_outputs):
    ensemble_input = dict()
    for tagger_output in external_tagger_outputs:
        identifier, grammar_pattern = tagger_output.split(',')
        identifier_grammarPattern = zip(identifier.split(), grammar_pattern.split())
        i = 0
        for word_gp_pair in identifier_grammarPattern:
            if word_gp_pair[0]+str(i) in ensemble_input:
                ensemble_input[word_gp_pair[0]+str(i)].append(word_gp_pair[1])
            else:
                ensemble_input[word_gp_pair[0]+str(i)] = [word_gp_pair[1]]
            i = i + 1
    root_logger.debug("Final ensemble input: {identifierDat}".format(identifierDat=ensemble_input))
    return ensemble_input
        

    
def run_external_taggers(identifier_data, context_of_identifier):
    external_tagger_outputs = []
    #split and process identifier data into external tagger outputs
    external_tagger_outputs.append(process_identifier_with_swum(identifier_data, context_of_identifier))
    external_tagger_outputs.append(process_identifier_with_posse(identifier_data, context_of_identifier))
    external_tagger_outputs.append(process_identifier_with_stanford(identifier_data, context_of_identifier))
    root_logger.debug("raw ensemble input: {identifierDat}".format(identifierDat=external_tagger_outputs))
    return generate_ensemble_tagger_input_format(external_tagger_outputs)

def categorize(key_swum, key_posse, key_stanford):
    #DTCP or RFCP
    #select * from training_set_conj order by random()
    swum = {'D':0, 'DT':1, 'FAILURE':2, 'N':3, 'NM':4, 'P':5, 'PR':6, 'PRE':7, 'V':8}
    posse = {'DT':0, 'FAILURE':1, 'N':2, 'NM':3, 'P':4, 'PR':5, 'V':6}
    stanford = {'CJ':0, 'D':1, 'DT':2, 'FAILURE':3, 'N':4, 'NM':5, 'NPL':6, 'P':7, 'PR':8, 'V':9, 'VBD':10, 'VBG':11, 'VBN':12, 'VBP':13, 'VBZ':14, 'VM':15}

    #DTCA or RFCA
    #select * from training_set_conj_other order by random()
    # swum = {'D':0, 'FAILURE':1, 'N':2, 'NM':3, 'OTHER':4, 'P':5, 'PRE':6, 'V':7, 'PR':8}
    # posse = {'FAILURE':0, 'N':1, 'NM':2, 'OTHER':3, 'P':4, 'V':5}
    # stanford = {'D':0, 'FAILURE':1, 'N':2, 'NM':3, 'NPL':4, 'OTHER':5, 'P':6, 'V':7, 'VBD':8, 'VBG':9, 'VBN':10, 'VBP':11, 'VBZ':12}

    #DTNP or RFNP
    #select * from training_set_norm order by random()
    # swum = {'D':0, 'DT':1, 'FAILURE':2, 'N':3, 'NM':4, 'P':5, 'PR':6, 'PRE':7, 'V':8}
    # posse = {'DT':0, 'FAILURE':1, 'N':2, 'NM':3, 'P':4, 'PR':5, 'V':6}
    # stanford = {'CJ':0, 'D':1, 'DT':2, 'N':3, 'NM':4, 'NPL':5, 'P':6, 'PR':7, 'V':8, 'VM':9, 'FAILURE':10}

    #DTNA or RFNA
    # #select * from training_set_norm_other order by random()
    # swum = {'FAILURE':0, 'N':1, 'NM':2, 'OTHER':3, 'P':4, 'PRE':5, 'V':6, 'PR':7}
    # posse = {'FAILURE':0, 'N':1, 'NM':2, 'OTHER':3, 'P':4, 'V':5}
    # stanford = {'N':0, 'NM':1, 'NPL':2, 'OTHER':3, 'P':4, 'V':5,'FAILURE':6}

    return swum.get(key_swum), posse.get(key_posse), stanford.get(key_stanford)


def annotate_word(swum_tag, posse_tag, stanford_tag, normalized_length, code_context):
    input_model = 'models/model_DecisionTreeClassifier_training_set_conj.pkl'        #DTCP
    #input_model = 'models/model_RandomForestClassifier_training_set_conj.pkl'       #RFCP
    #input_model = 'models/model_DecisionTreeClassifier_training_set_conj_other.pkl' #DTCA
    #input_model = 'models/model_RandomForestClassifier_training_set_conj_other.pkl' #RFCA
    #input_model = 'models/model_DecisionTreeClassifier_training_set_norm.pkl'       #DTNP
    #input_model = 'models/model_RandomForestClassifier_training_set_norm.pkl'       #RFNP
    #input_model = 'models/model_DecisionTreeClassifier_training_set_norm_other.pkl' #DTNA
    #input_model = 'models/model_RandomForestClassifier_training_set_norm_other.pkl' #RFNA

    # if len(sys.argv) < 2:
    #     print("Syntax: python3 model_classification.py [model]")
    #     quit()
    swum, posse, stanford = categorize(swum_tag, posse_tag, stanford_tag)

    data = {'SWUM_TAG': [swum],
            'POSSE_TAG': [posse],
            'STANFORD_TAG': [stanford],
            'NORMALIZED_POSITION': [normalized_length],
            'CONTEXT': [code_context]
            }

    df_features = pd.DataFrame(data,
                               columns=['SWUM_TAG', 'POSSE_TAG', 'STANFORD_TAG', 'NORMALIZED_POSITION', 'CONTEXT'])

    clf = joblib.load(input_model)
    y_pred = clf.predict(df_features)
    return (y_pred[0])

#read_from_cmd_line()