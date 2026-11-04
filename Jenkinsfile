pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        PYTHONUNBUFFERED = '1'
        REGISTRY_NAME    = 'python-crud-api'
        CONTAINER_NAME   = 'production-api-container'
        PORT_MAPPING     = '5000:5000'
        VOLUME_NAME      = 'production-api-data'
        // Jenkins berjalan di dalam container: "localhost" di sini adalah container Jenkins,
        // bukan host Docker. Port 5000 yang di-publish dijangkau lewat host.docker.internal.
        HEALTH_URL       = 'http://host.docker.internal:5000/health'
    }

    stages {
        stage('1. Checkout Code') {
            steps {
                echo 'Checking out source code from GitHub'
                checkout scm
                script {
                    env.GIT_SHA = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                }
                echo "Commit: ${env.GIT_SHA}"
            }
        }

        stage('2. Code Syntax Verification') {
            steps {
                sh 'python3 -m py_compile app.py tests/test_app.py'
            }
        }

        stage('3. Unit Test') {
            steps {
                sh 'python3 -m unittest discover -s tests -v'
            }
        }

        stage('4. Build Docker Image') {
            steps {
                // Tag: nomor build, commit SHA, dan latest
                sh '''
                    docker build --build-arg APP_VERSION=${BUILD_NUMBER}-${GIT_SHA} \
                        -t ${REGISTRY_NAME}:${BUILD_NUMBER} \
                        -t ${REGISTRY_NAME}:${GIT_SHA} \
                        -t ${REGISTRY_NAME}:latest .
                    docker image ls ${REGISTRY_NAME}
                '''
            }
        }

        stage('5. Automated Deployment') {
            steps {
                script {
                    // Simpan image yang sedang berjalan untuk rollback jika health check gagal
                    env.PREVIOUS_IMAGE = sh(
                        script: 'docker inspect -f "{{.Config.Image}}" ${CONTAINER_NAME} 2>/dev/null || true',
                        returnStdout: true).trim()
                    echo "Image sebelumnya: ${env.PREVIOUS_IMAGE ?: '(belum ada)'}"
                }
                sh '''
                    docker stop ${CONTAINER_NAME} || true
                    docker rm ${CONTAINER_NAME} || true
                    docker volume create ${VOLUME_NAME}
                    docker run -d \
                        --name ${CONTAINER_NAME} \
                        -p ${PORT_MAPPING} \
                        -v ${VOLUME_NAME}:/var/lib/backend_data \
                        --restart unless-stopped \
                        ${REGISTRY_NAME}:${BUILD_NUMBER}
                '''
                script { env.DEPLOYED = 'true' }
            }
        }

        stage('6. Health Check') {
            steps {
                sh '''
                    echo "Menunggu Docker HEALTHCHECK..."
                    for i in $(seq 1 20); do
                        STATUS=$(docker inspect -f '{{.State.Health.Status}}' ${CONTAINER_NAME})
                        echo "  percobaan $i: $STATUS"
                        [ "$STATUS" = "healthy" ] && break
                        sleep 2
                    done
                    [ "$STATUS" = "healthy" ]

                    echo "Health check dari Jenkins melalui port yang di-publish:"
                    curl -fsS ${HEALTH_URL}
                    echo
                    docker logs --tail 20 ${CONTAINER_NAME}
                '''
            }
        }
    }

    post {
        success {
            echo "Pipeline completed successfully. Image ${REGISTRY_NAME}:${BUILD_NUMBER} (commit ${env.GIT_SHA})"
        }
        failure {
            script {
                if (env.DEPLOYED == 'true' && env.PREVIOUS_IMAGE) {
                    echo "Rollback ke image sebelumnya: ${env.PREVIOUS_IMAGE}"
                    sh '''
                        docker rm -f ${CONTAINER_NAME} || true
                        docker run -d \
                            --name ${CONTAINER_NAME} \
                            -p ${PORT_MAPPING} \
                            -v ${VOLUME_NAME}:/var/lib/backend_data \
                            --restart unless-stopped \
                            ${PREVIOUS_IMAGE}
                    '''
                }
            }
            echo 'Pipeline failed. Inspect Console Output.'
        }
    }
}
