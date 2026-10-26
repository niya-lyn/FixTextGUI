<?php

use App\Service\Note\WordsGenerator;

chdir(__DIR__);

include("autoload.php");

echo (new WordsGenerator)->convertByFixedNoteRules($argv[1], $argv[2]);
