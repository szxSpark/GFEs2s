import logging
import torch
import models
import re

try:
    import ipdb
except ImportError:
    pass

lower = True
seq_length = None  # english
report_every = 1000
shuffle = 1


logger = logging.getLogger(__name__)

def makeVocabulary(filenames, size):
    vocab = models.Dict([utils.Constants.PAD_WORD, utils.Constants.UNK_WORD,
                         utils.Constants.BOS_WORD, utils.Constants.EOS_WORD], lower=lower)
    for filename in filenames:
        with open(filename, encoding='utf-8') as f:
            for sent in f.readlines():
                for word in sent.strip().split(' '):
                    vocab.add(word)

    originalSize = vocab.size()
    vocab = vocab.prune(size)
    logger.info('Created dictionary of size %d (pruned from %d)' %
                (vocab.size(), originalSize))

    return vocab


def initVocabulary(name, dataFiles, vocabFile, vocabSize):
    vocab = None
    if vocabFile is not None:
        # If given, load existing word dictionary.
        logger.info('Reading ' + name + ' vocabulary from \'' + vocabFile + '\'...')
        vocab = models.Dict()
        vocab.loadFile(vocabFile)
        logger.info('Loaded ' + str(vocab.size()) + ' ' + name + ' words')

    if vocab is None:
        # If a dictionary is still missing, generate it.
        logger.info('Building ' + name + ' vocabulary...')
        genWordVocab = makeVocabulary(dataFiles, vocabSize)

        vocab = genWordVocab

    return vocab


def saveVocabulary(name, vocab, file):
    logger.info('Saving ' + name + ' vocabulary to \'' + file + '\'...')
    vocab.writeFile(file)


def article2ids(article_words, vocab):
    ids = []
    oovs = []
    unk_id = vocab.lookup(utils.Constants.UNK_WORD)
    for w in article_words:
        i = vocab.lookup(w, unk_id)  # 查不到默认unk
        if i == unk_id:  # oov
            if w not in oovs:
                oovs.append(w)
            oov_num = oovs.index(w) # This is 0 for the first article OOV, 1 for the second article OOV...
            ids.append(vocab.size() + oov_num)
        else:
            ids.append(i)
    return ids, oovs


def abstract2ids(abstract_words, vocab, article_oovs):
    ids = []
    unk_id = vocab.lookup(utils.Constants.UNK_WORD)
    for w in abstract_words:
        i = vocab.lookup(w, unk_id)  # 查不到默认unk
        if i == unk_id:  # If w is an OOV word
            if w in article_oovs:  # If w is an in-article OOV
                vocab_idx = vocab.size() + article_oovs.index(w)  # Map to its temporary article OOV number
                ids.append(vocab_idx)
            else:  # If w is an out-of-article OOV
                ids.append(unk_id)  # Map to the UNK token id
        else:
            ids.append(i)
    return ids

def split_sentences(article):
    '''
    对文章分句
    :param article: str
    :return: list(str)
    '''
    article = article.strip()
    para = re.sub('([。！!？?\?])([^”’])', r"\1\n\2", article)  # 单字符断句符
    para = re.sub('(\.{6})([^”’])', r"\1\n\2", para)  # 英文省略号
    para = re.sub('(\…{2})([^”’])', r"\1\n\2", para)  # 中文省略号
    para = re.sub('([。！!？?\?][”’])([^，。！!？?\?])', r'\1\n\2', para)
    para = para.rstrip()
    return para.split("\n")

def makeData(srcFile, tgtFile, srcDicts, tgtDicts, pointer_gen=False):
    src, tgt = [], []
    sizes = []
    src_extend_vocab, tgt_extend_vocab = [], []
    src_oovs_list = []
    count, ignored = 0, 0
    logger.info('Processing %s & %s ...' % (srcFile, tgtFile))

    srcF = open(srcFile, encoding='utf-8')
    tgtF = open(tgtFile, encoding='utf-8')
    while True:
        sline = srcF.readline().strip()
        tline = tgtF.readline().strip()

        # normal end of file
        if sline == "" and tline == "":
            break

        # source or target does not have same number of lines
        if sline == "" or tline == "":
            logger.info('WARNING: source and target do not have the same number of sentences')
            break

        # source and/or target are empty
        if sline == "" or tline == "":
            logger.info('WARNING: ignoring an empty line (' + str(count + 1) + ')')
            continue

        srcWords = sline.split(' ')
        tgtWords = tline.split(' ')

        srcWords = srcWords[:seq_length]  # TODO 截断
        tgtWords = tgtWords[:seq_length]  # TODO 截断

        # if len(srcWords) <= seq_length and len(tgtWords) <= seq_length:
        if True:
            # TODO 截断
            src += [srcDicts.convertToIdx(srcWords,
                                          utils.Constants.UNK_WORD)]  # [Tensor]
            tgt += [tgtDicts.convertToIdx(tgtWords,
                                          utils.Constants.UNK_WORD,
                                          utils.Constants.BOS_WORD,
                                          utils.Constants.EOS_WORD)]  # 添加特殊token
            sizes += [len(srcWords)]


            if pointer_gen:
                # 存储临时的oov词典
                enc_input_extend_vocab, article_oovs = article2ids(srcWords, srcDicts)
                abs_ids_extend_vocab = abstract2ids(tgtWords, tgtDicts, article_oovs)
                # 覆盖target，用于使用临时词典
                vec = []
                vec += [srcDicts.lookup(utils.Constants.BOS_WORD)]
                vec += abs_ids_extend_vocab
                vec += [srcDicts.lookup(utils.Constants.EOS_WORD)]
                src_extend_vocab += [enc_input_extend_vocab]
                src_oovs_list += [article_oovs]
                tgt_extend_vocab.append(torch.LongTensor(vec))

        else:
            ignored += 1

        count += 1

        if count % report_every == 0:
            logger.info('... %d sentences prepared' % count)

    srcF.close()
    tgtF.close()

    if shuffle == 1:
        logger.info('... shuffling sentences')
        perm = torch.randperm(len(src)) # eg, 4: [0,2,3,1]
        src = [src[idx] for idx in perm]
        tgt = [tgt[idx] for idx in perm]
        sizes = [sizes[idx] for idx in perm]

        if pointer_gen:
            src_extend_vocab = [src_extend_vocab[idx] for idx in perm]
            tgt_extend_vocab = [tgt_extend_vocab[idx] for idx in perm]
            src_oovs_list = [src_oovs_list[idx] for idx in perm]

    logger.info('... sorting sentences by size')
    _, perm = torch.sort(torch.Tensor(sizes))
    src = [src[idx] for idx in perm]
    tgt = [tgt[idx] for idx in perm]

    if pointer_gen:
        src_extend_vocab = [src_extend_vocab[idx] for idx in perm]
        tgt_extend_vocab = [tgt_extend_vocab[idx] for idx in perm]
        src_oovs_list = [src_oovs_list[idx] for idx in perm]

    logger.info('Prepared %d sentences (%d ignored due to length == 0 or > %d)' %
                (len(src), ignored, seq_length))

    return src, tgt, (src_extend_vocab, tgt_extend_vocab, src_oovs_list)  # list(Tensor)


def prepare_data_online(train_src, src_vocab, train_tgt, tgt_vocab, pointer_gen):
    dicts = {}
    dicts['src'] = initVocabulary('source', [train_src], src_vocab, 0)
    dicts['tgt'] = initVocabulary('target', [train_tgt], tgt_vocab, 0)

    logger.info('Preparing training ...')
    train = {}
    train['src'], train['tgt'], (train['src_extend_vocab'], train['tgt_extend_vocab'], train['src_oovs_list'])\
        = makeData(train_src, train_tgt, dicts['src'], dicts['tgt'], pointer_gen)

    # enc_input_extend_vocab: source带有oov的id，oov相对于source_vocab
    # tgt_extend_vocab: tgt带有oov的id，oov相对于tgt_vocab
    # src_oovs_list： source里不再词典里的词
    dataset = {'dicts': dicts,
               'train': train,}
    return dataset
