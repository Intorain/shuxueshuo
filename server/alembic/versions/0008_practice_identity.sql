LOCK TABLE student_learning_marks IN ACCESS EXCLUSIVE MODE;
CREATE TEMP TABLE practice_id_migration (old_id text PRIMARY KEY, new_id text UNIQUE NOT NULL) ON COMMIT DROP;
INSERT INTO practice_id_migration VALUES
('q01', 'basic-inequality-q01'),
('q02', 'basic-inequality-q02'),
('q03', 'basic-inequality-q03'),
('q04', 'basic-inequality-q04'),
('q05', 'basic-inequality-q05'),
('q06', 'basic-inequality-q06'),
('q07', 'basic-inequality-q07'),
('q08', 'basic-inequality-q08'),
('q09', 'basic-inequality-q09'),
('q10', 'basic-inequality-q10'),
('q11', 'basic-inequality-q11'),
('q12', 'basic-inequality-q12'),
('q13', 'basic-inequality-q13'),
('q14', 'basic-inequality-q14'),
('q15', 'basic-inequality-q15'),
('q16', 'basic-inequality-q16'),
('q17', 'basic-inequality-q17'),
('q18', 'basic-inequality-q18'),
('q19', 'basic-inequality-q19'),
('q20', 'basic-inequality-q20'),
('q21', 'basic-inequality-q21'),
('q22', 'basic-inequality-q22'),
('q23', 'basic-inequality-q23'),
('q24', 'basic-inequality-q24'),
('q25', 'basic-inequality-q25'),
('q26', 'basic-inequality-q26'),
('q27', 'basic-inequality-q27'),
('q28', 'basic-inequality-q28'),
('q29', 'basic-inequality-q29'),
('q30', 'basic-inequality-q30');
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM student_learning_marks a
 JOIN practice_id_migration m ON m.old_id=a.problem_id
 JOIN student_learning_marks b ON b.user_id=a.user_id AND b.problem_id=m.new_id)
 THEN RAISE EXCEPTION 'Conflicting old/new learning marks; review before migrating'; END IF;
END $$;
UPDATE student_learning_marks s SET problem_id=m.new_id
FROM practice_id_migration m WHERE s.problem_id=m.old_id;
